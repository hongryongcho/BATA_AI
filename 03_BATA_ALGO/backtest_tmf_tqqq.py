"""
TMF + TQQQ 그리드 분할매수/매도 백테스트  (2021-01-01 ~ today)

[전략 요약]
  사이클 시작 : 자산 30% → TMF, 70% → TQQQ 그리드 풀 (N개 슬롯)
  그리드 매수 : 52주 최고가 기준 MDD -i×S% 도달 시, 해당 슬롯이 비어있으면 매수
  그리드 매도 : 각 슬롯의 매수가 대비 +S% 회복 시 개별 매도 → 슬롯 즉시 재사용 가능
  긴급 #1    : N개 슬롯 동시 전부 점유 → TMF 5%씩 6 Lot 분할매도 후 각각 TQQQ 매수
               (lot1: 슬롯 전부 점유 시 / lot2~6: 직전 긴급매수가 대비 -S% 마다)
  긴급 #2    : TMF 6 Lot 전량 소진 후 → 잔여현금 절반 매수(lot A), 추가 -S% 하락 시 나머지 매수(lot B)
  가상매수   : 긴급 #1·#2 모두 완료 후 현금=0인 상태에서 추가 하락 → 마진 가상 매수
  매도 순서  : 그리드 슬롯 매도 완료 후 긴급 lot 매도 (폭락 구간 저점 매수 → 회복 구간 대량 매도)
  사이클 종료 : TQQQ ≥ ref_high × (1+S%) → 전체 포지션 청산 → 리밸런싱
  양도세     : 연간 실현손익 22% (비과세 $1,900), 사이클 종료 시 직전 연도분 차감
"""

import sys
import time
import itertools
from pathlib import Path
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
from _env_loader import get_service_account_path, load_env_config

# ── 상수 ─────────────────────────────────────────────────────────────────────
TAX_RATE          = 0.22
TAX_EXEMPTION     = 1_900.0
INITIAL_CAPITAL   = 100_000.0
TMF_RATIO         = 0.30
START_DATE        = "2021-01-01"
SPREADSHEET_TITLE = "TMF_TQQQ_분할매수_백테스트"
USER_EMAIL        = "hongryong.cho@gmail.com"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── 데이터 클래스 ─────────────────────────────────────────────────────────────
@dataclass
class Lot:
    buy_date:        str
    buy_price:       float
    shares:          float
    cost:            float
    level:           int    # 1..N = 그리드; -1 = TMF긴급; -2 = 수익금긴급
    buy_mdd:         float
    sell_target_mdd: float  # 999 = 사이클 종료까지 보유
    is_virtual:      bool = False  # True = 가상매수 (긴급#2 이후 현금 부족 시 마진)

@dataclass
class DayRec:
    date:             str
    tqqq_price:       float
    tmf_price:        float
    mdd_pct:          float
    cycle_num:        int
    slots_open:       int    # 실제 점유 슬롯 수
    virtual_slots:    int    # 가상매수 슬롯 수
    emerg_lots_open:  int
    tqqq_value:       float
    tmf_value:        float
    cash:             float
    total_assets:     float
    total_return_pct: float
    action:           str


# ── 데이터 다운로드 ───────────────────────────────────────────────────────────
def load_data() -> Tuple[pd.Series, pd.Series]:
    print("[data] TQQQ + TMF 다운로드 (52주 lookback용 2020-01~)...")
    raw  = yf.download(["TQQQ", "TMF"], start="2020-01-01", auto_adjust=True, progress=False)
    tqqq = raw["Close"]["TQQQ"].dropna()
    tmf  = raw["Close"]["TMF"].dropna()
    idx  = tqqq.index.intersection(tmf.index)
    print(f"[data] 공통 거래일 {len(idx)}일")
    return tqqq.loc[idx], tmf.loc[idx]


# ── 시뮬레이션 (그리드 매매) ──────────────────────────────────────────────────
def simulate(
    tqqq_s: pd.Series,
    tmf_s:  pd.Series,
    step:   float = 0.025,
    n:      int   = 20,
    start:  str   = START_DATE,
    end:    str   = None,
) -> Tuple[List[DayRec], List[dict], dict]:

    all_idx   = tqqq_s.index
    start_ts  = pd.Timestamp(start)
    end_ts    = pd.Timestamp(end or str(date.today()))
    trade_idx = all_idx[(all_idx >= start_ts) & (all_idx <= end_ts)]
    if len(trade_idx) == 0:
        raise ValueError(f"거래일 없음: {start}~{end}")

    # ── 사이클 상태 ──────────────────────────────────────────────────────────
    cycle_num         = [0]
    ref_high          = [0.0]
    new_high_thr      = [0.0]
    lot_size          = [0.0]   # 사이클 시작 시 고정: trd_alloc / N
    tmf_shares        = [0.0]
    tmf_cost          = [0.0]
    c_cash            = [0.0]   # 미투자 현금 (매도 수익 복귀)
    tmf_sold          = [False]  # TMF 6 Lot 전량 소진 여부
    profit_done       = [False]  # 현금 긴급 Lot 2개 전량 소진 여부
    c_gains           = [0.0]
    virtual_used      = [False]  # 이번 사이클에 가상매수 발생 여부
    c_start_date      = [""]
    c_start_assets    = [0.0]
    # 긴급 분할 매수 추가 상태
    tmf_lots_done     = [0]      # 0..6: TMF 긴급 lot 투입 수
    tmf_lot_shares0   = [0.0]    # TMF 총 보유 수량 / 6 (lot당 고정 수량)
    tmf_cost_per_lot  = [0.0]    # TMF 원가 / 6 (lot당 고정 원가)
    last_emerg_buy    = [0.0]    # 마지막 긴급매수 가격 (TMF lot 또는 현금 lot)
    cash_emerg_done   = [0]      # 0, 1, 2: 현금 긴급 lot 투입 수

    # slots[i] = Lot or None (i = 1..N)
    slots:      Dict[int, Optional[Lot]] = {}
    emerg_lots: List[Lot]                = []

    # ── 세금 상태 ─────────────────────────────────────────────────────────────
    gains_by_yr: Dict[int, float] = {}
    tax_by_yr:   Dict[int, float] = {}
    pending_tax: set               = set()

    day_recs:   List[DayRec] = []
    cycle_recs: List[dict]   = []

    def get_52w_high(pos: int) -> float:
        s = max(0, pos - 251)
        return float(tqqq_s.iloc[s: pos + 1].max())

    def init_cycle(pos: int, assets: float):
        cycle_num[0]      += 1
        c_start_date[0]    = str(all_idx[pos].date())
        c_start_assets[0]  = assets
        tp = float(tqqq_s.iloc[pos])
        mp = float(tmf_s.iloc[pos])
        ref_high[0]        = get_52w_high(pos)
        new_high_thr[0]    = ref_high[0] * (1.0 + step)
        trd_alloc          = assets * (1.0 - TMF_RATIO)
        lot_size[0]        = trd_alloc / n
        tmf_shares[0]      = (assets * TMF_RATIO) / mp
        tmf_cost[0]        = assets * TMF_RATIO
        c_cash[0]          = trd_alloc
        slots.clear()
        for i in range(1, n + 1):
            slots[i] = None
        emerg_lots.clear()
        tmf_sold[0]          = False
        profit_done[0]       = False
        c_gains[0]           = 0.0
        virtual_used[0]      = False
        tmf_lots_done[0]     = 0
        tmf_lot_shares0[0]   = 0.0
        tmf_cost_per_lot[0]  = 0.0
        last_emerg_buy[0]    = 0.0
        cash_emerg_done[0]   = 0

    first_pos = all_idx.get_loc(trade_idx[0])
    init_cycle(first_pos, INITIAL_CAPITAL)
    prev_yr = None

    for dt in trade_idx:
        pos = all_idx.get_loc(dt)
        tp  = float(tqqq_s.iloc[pos])
        mp  = float(tmf_s.iloc[pos])
        dts = str(dt.date())
        yr  = dt.year

        if prev_yr is not None and yr != prev_yr:
            pending_tax.add(prev_yr)

        mdd     = (tp - ref_high[0]) / ref_high[0]
        actions = []

        # ── 1a. 그리드 매도: 목표 MDD 회복 슬롯 매도 → 슬롯 재사용 가능 ───────
        for lvl in sorted(slots.keys()):
            lot = slots[lvl]
            if lot is not None and not lot.is_virtual and mdd >= lot.sell_target_mdd:
                slots[lvl] = None
                proceeds = lot.shares * tp
                gain     = proceeds - lot.cost
                c_gains[0]     += gain
                c_cash[0]      += proceeds
                gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
                actions.append(f"SELL-L{lvl}@{tp:.2f}(+{gain:.0f})")

        # ── 1b. 긴급 매도: #2(잉여현금) 먼저, 그 다음 #1(TMF매도분) ───────────
        # sell_target_mdd 오름차순(가장 깊은 것 먼저) → 자연스럽게 #2 → #1 순서
        to_sell_e = [el for el in emerg_lots if mdd >= el.sell_target_mdd]
        emerg_lots[:] = [el for el in emerg_lots if mdd < el.sell_target_mdd]
        for el in sorted(to_sell_e, key=lambda e: e.sell_target_mdd):
            proceeds = el.shares * tp
            gain     = proceeds - el.cost
            c_gains[0]     += gain
            c_cash[0]      += proceeds
            gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
            ltype = "ESELL2" if el.level == -2 else "ESELL1"
            actions.append(f"{ltype}@{tp:.2f}(+{gain:.0f})")

        # ── 1c. 가상 슬롯 매도: 긴급 lot가 모두 소진된 이후에만 ─────────────
        if not emerg_lots:
            for lvl in sorted(slots.keys()):
                lot = slots[lvl]
                if lot is not None and lot.is_virtual and mdd >= lot.sell_target_mdd:
                    slots[lvl] = None
                    actions.append(f"VSELL-L{lvl}@{tp:.2f}")

        # ── 2. 그리드 매수: 빈 슬롯 중 해당 레벨 도달 시 매수 ─────────────────
        # 가상 모드: 현재 MDD에 해당하는 레벨까지 슬롯 동적 확장 (N+1 이상)
        virtual_active = tmf_sold[0] and profit_done[0]
        if virtual_active and mdd < -step * 0.5:
            deepest_lvl = min(int(abs(mdd) / step) + 1, n + 40)
        else:
            deepest_lvl = n

        for lvl in range(1, deepest_lvl + 1):
            trig = -lvl * step
            if slots.get(lvl) is None and mdd <= trig:
                if lvl <= n and c_cash[0] >= lot_size[0] - 0.01:
                    # 실제 매수: 레벨 1..N 한정, lot_size = 70%/N 고정
                    sh = lot_size[0] / tp
                    slots[lvl] = Lot(
                        buy_date=dts, buy_price=tp, shares=sh,
                        cost=lot_size[0], level=lvl, buy_mdd=trig,
                        sell_target_mdd=trig + step,
                    )
                    c_cash[0] -= lot_size[0]
                    actions.append(f"BUY-L{lvl}@{tp:.2f}")
                elif virtual_active:
                    # 가상매수: 레벨 N+1 이상이거나 현금 부족 시 → 슬롯만 점유
                    slots[lvl] = Lot(
                        buy_date=dts, buy_price=tp, shares=0.0,
                        cost=0.0, level=lvl, buy_mdd=trig,
                        sell_target_mdd=trig + step,
                        is_virtual=True,
                    )
                    virtual_used[0] = True
                    actions.append(f"VBUY-L{lvl}@{tp:.2f}")

        # ── 3. 긴급 #1: TMF 6분할 (5%씩) → TQQQ 매수 ───────────────────────────
        # lot1 트리거: 모든 N개 슬롯 동시 점유
        # lot2~6 트리거: 직전 긴급매수가 대비 -S% 추가 하락
        all_full = all(slots.get(i) is not None for i in range(1, n + 1))
        first_emerg_trigger = (all_full and tmf_lots_done[0] == 0 and tmf_shares[0] > 0)
        next_emerg_trigger  = (1 <= tmf_lots_done[0] < 6
                                and tmf_shares[0] > 0
                                and last_emerg_buy[0] > 0
                                and tp <= last_emerg_buy[0] * (1.0 - step))
        if first_emerg_trigger or next_emerg_trigger:
            if tmf_lots_done[0] == 0:
                tmf_lot_shares0[0]  = tmf_shares[0] / 6
                tmf_cost_per_lot[0] = tmf_cost[0] / 6
            lot_sh   = min(tmf_lot_shares0[0], tmf_shares[0])
            lot_cost = min(tmf_cost_per_lot[0], tmf_cost[0])
            procs    = lot_sh * mp
            gain     = procs - lot_cost
            gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
            c_gains[0]     += gain
            sh = procs / tp
            tmf_lots_done[0] += 1
            emerg_lots.append(Lot(
                buy_date=dts, buy_price=tp, shares=sh,
                cost=procs, level=-1, buy_mdd=mdd,
                sell_target_mdd=mdd + step,
            ))
            tmf_shares[0]    -= lot_sh
            tmf_cost[0]      -= lot_cost
            last_emerg_buy[0] = tp
            if tmf_lots_done[0] >= 6:
                tmf_sold[0] = True
            actions.append(f"EMERG1-L{tmf_lots_done[0]}@{tp:.2f}(TMF={procs:.0f})")

        # ── 4. 긴급 #2: 잔여현금 2분할 → TQQQ 매수 ─────────────────────────────
        # lot A (절반): TMF 전량 소진 후 직전 긴급매수가 대비 -S% 하락 시
        # lot B (나머지): lot A 매수가 대비 -S% 추가 하락 시
        if (tmf_sold[0] and cash_emerg_done[0] < 2
                and last_emerg_buy[0] > 0 and c_cash[0] > 1.0
                and tp <= last_emerg_buy[0] * (1.0 - step)):
            invest = c_cash[0] / 2 if cash_emerg_done[0] == 0 else c_cash[0]
            sh     = invest / tp
            cash_emerg_done[0] += 1
            emerg_lots.append(Lot(
                buy_date=dts, buy_price=tp, shares=sh,
                cost=invest, level=-2, buy_mdd=mdd,
                sell_target_mdd=mdd + step,
            ))
            c_cash[0]         -= invest
            last_emerg_buy[0]  = tp
            if cash_emerg_done[0] >= 2:
                profit_done[0] = True
            actions.append(f"EMERG2-L{cash_emerg_done[0]}@{tp:.2f}(cash={invest:.0f})")

        # ── 5. 사이클 종료: 52주 최고가 +S% 갱신 ────────────────────────────────
        if tp >= new_high_thr[0]:
            # 남은 그리드 슬롯 전량 청산 (가상 lot는 현금 영향 없이 슬롯만 해제)
            for lvl in sorted(slots.keys()):
                lot = slots[lvl]
                if lot is not None:
                    if not lot.is_virtual:
                        procs = lot.shares * tp
                        gain  = procs - lot.cost
                        c_gains[0] += gain
                        c_cash[0]  += procs
                        gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
                    slots[lvl] = None

            # 긴급 lot 전량 매도 (나중: 그리드 청산 후 긴급 lot 매도)
            for el in emerg_lots:
                procs = el.shares * tp
                gain  = procs - el.cost
                c_gains[0] += gain
                c_cash[0]  += procs
                gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
                actions.append(f"EMERG-SELL@{tp:.2f}(+{gain:.0f})")
            emerg_lots.clear()

            # 남은 TMF 매도
            if tmf_shares[0] > 0:
                procs = tmf_shares[0] * mp
                gain  = procs - tmf_cost[0]
                gains_by_yr[yr] = gains_by_yr.get(yr, 0) + gain
                c_gains[0] += gain
                c_cash[0]  += procs
                tmf_shares[0] = 0.0

            total_end = c_cash[0]

            # 직전 연도 양도세 차감
            for ty in sorted(pending_tax):
                g   = gains_by_yr.get(ty, 0)
                tax = max(0.0, (g - TAX_EXEMPTION) * TAX_RATE)
                if tax > 0:
                    total_end -= tax
                    tax_by_yr[ty] = tax_by_yr.get(ty, 0) + tax
                    actions.append(f"TAX-{ty}:${tax:.0f}")
            pending_tax.clear()
            total_end = max(total_end, 0.0)

            ret_pct = (total_end / c_start_assets[0] - 1) * 100
            cycle_recs.append({
                "cycle":            cycle_num[0],
                "start_date":       c_start_date[0],
                "end_date":         dts,
                "start_assets":     c_start_assets[0],
                "end_assets":       total_end,
                "return_pct":       ret_pct,
                "realized_gains":   c_gains[0],
                "emerg1_lots":      tmf_lots_done[0],
                "emerg2_lots":      cash_emerg_done[0],
                "virtual_used":     virtual_used[0],
            })
            actions.append(f"CYCLE-END#{cycle_num[0]}({ret_pct:.1f}%)")

            init_cycle(pos, total_end)
            actions.append(f"CYCLE-START#{cycle_num[0]}")

        # ── EOD 자산 평가 ─────────────────────────────────────────────────────
        slots_val = sum(l.shares * tp for l in slots.values() if l is not None)
        emerg_val = sum(l.shares * tp for l in emerg_lots)
        tmf_val   = tmf_shares[0] * mp
        total_eod = c_cash[0] + slots_val + emerg_val + tmf_val

        day_recs.append(DayRec(
            date=dts, tqqq_price=tp, tmf_price=mp,
            mdd_pct=mdd * 100, cycle_num=cycle_num[0],
            slots_open=sum(1 for l in slots.values() if l is not None and not l.is_virtual),
            virtual_slots=sum(1 for l in slots.values() if l is not None and l.is_virtual),
            emerg_lots_open=len(emerg_lots),
            tqqq_value=slots_val + emerg_val, tmf_value=tmf_val,
            cash=c_cash[0], total_assets=total_eod,
            total_return_pct=(total_eod / INITIAL_CAPITAL - 1) * 100,
            action="|".join(actions) if actions else "HOLD",
        ))

        prev_yr = yr

    final = day_recs[-1].total_assets if day_recs else INITIAL_CAPITAL
    yrs   = max((end_ts - start_ts).days / 365.25, 0.1)
    cagr  = ((final / INITIAL_CAPITAL) ** (1.0 / yrs) - 1.0) * 100

    return day_recs, cycle_recs, {
        "step_pct":         step * 100,
        "n_splits":         n,
        "initial_capital":  INITIAL_CAPITAL,
        "final_assets":     final,
        "total_return_pct": (final / INITIAL_CAPITAL - 1) * 100,
        "cagr_pct":         cagr,
        "total_cycles":     len(cycle_recs),
        "tax_paid":         sum(tax_by_yr.values()),
    }


# ── 연도별 수익률 ─────────────────────────────────────────────────────────────
def calc_yearly(day_recs: List[DayRec]) -> Dict[int, dict]:
    if not day_recs:
        return {}
    by_yr: Dict[int, List[DayRec]] = {}
    for r in day_recs:
        by_yr.setdefault(int(r.date[:4]), []).append(r)
    result, prev = {}, INITIAL_CAPITAL
    for yr in sorted(by_yr):
        end = by_yr[yr][-1].total_assets
        result[yr] = {"start": prev, "end": end,
                      "return_pct": (end / prev - 1) * 100}
        prev = end
    return result


# ── 파라미터 그리드 탐색 ──────────────────────────────────────────────────────
def grid_search(
    tqqq_s: pd.Series,
    tmf_s:  pd.Series,
    steps:  list = None,
    splits: list = None,
) -> List[dict]:
    if steps  is None: steps  = [0.010, 0.015, 0.020, 0.025, 0.030, 0.040, 0.050]
    if splits is None: splits = [10, 12, 15, 18, 20, 25, 30]
    combos = list(itertools.product(steps, splits))
    print(f"[grid] {len(combos)}개 조합 탐색...")
    results = []
    for i, (s, n_) in enumerate(combos, 1):
        try:
            _, _, summary = simulate(tqqq_s, tmf_s, step=s, n=n_)
            results.append(summary)
            print(f"  [{i:2d}/{len(combos)}] S={s*100:.1f}% N={n_:2d} → "
                  f"CAGR={summary['cagr_pct']:.1f}%  "
                  f"수익={summary['total_return_pct']:.0f}%  "
                  f"사이클={summary['total_cycles']}")
        except Exception as e:
            print(f"  [{i:2d}/{len(combos)}] S={s*100:.1f}% N={n_:2d} → 오류: {e}")
    return results


# ── Google Sheets 공통 유틸 ───────────────────────────────────────────────────
def _gc():
    sa = Path(get_service_account_path())
    if not sa.is_absolute():
        sa = BASE_DIR / sa
    creds = Credentials.from_service_account_file(str(sa), scopes=SCOPES)
    return gspread.authorize(creds)

def _ws(ss, title: str, rows: int = 2000, cols: int = 20) -> gspread.Worksheet:
    try:
        return ss.worksheet(title)
    except gspread.WorksheetNotFound:
        return ss.add_worksheet(title=title, rows=rows, cols=cols)

def _hdr_fmt(sheet_id: int, row: int, n_cols: int) -> dict:
    return {"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": row - 1, "endRowIndex": row,
            "startColumnIndex": 0,    "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.13, "green": 0.19, "blue": 0.33},
            "textFormat": {
                "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                "bold": True,
            },
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }}

def _section_fmt(sheet_id: int, row: int, n_cols: int) -> dict:
    return {"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": row - 1, "endRowIndex": row,
            "startColumnIndex": 0,    "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {
            "backgroundColor": {"red": 0.85, "green": 0.90, "blue": 0.98},
            "textFormat": {"bold": True},
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }}

def _row_fmt(sheet_id: int, row: int, n_cols: int, bg: dict, bold: bool = False) -> dict:
    return {"repeatCell": {
        "range": {
            "sheetId": sheet_id,
            "startRowIndex": row - 1, "endRowIndex": row,
            "startColumnIndex": 0,    "endColumnIndex": n_cols,
        },
        "cell": {"userEnteredFormat": {
            "backgroundColor": bg,
            "textFormat": {"bold": bold},
        }},
        "fields": "userEnteredFormat(backgroundColor,textFormat)",
    }}

def _chunks(ws, start_row: int, rows: list, chunk: int = 500):
    for i in range(0, len(rows), chunk):
        ws.update(values=rows[i: i + chunk],
                  range_name=f"A{start_row + i}",
                  value_input_option="RAW")
        time.sleep(0.4)


# ── 탭 1: Algorithm ───────────────────────────────────────────────────────────
def write_algorithm(ws, step_pct: float, n: int):
    ws.clear()
    sid   = ws.id
    today = str(date.today())
    data  = [
        ["TMF + TQQQ 그리드 분할매수/매도 알고리즘"],
        [f"백테스트 기간: {START_DATE} ~ {today}"],
        [""],
        ["▶ 전략 개요"],
        ["항목", "내용"],
        ["전략 유형", "그리드 매매 (Grid Trading) 기반 스윙 전략"],
        ["기초 자산", "TMF (3x 미국채 ETF) + TQQQ (3x 나스닥 ETF)"],
        ["초기 자본", f"${INITIAL_CAPITAL:,.0f}"],
        ["TMF 비율", f"{TMF_RATIO*100:.0f}% (사이클 시작 시 매수)"],
        ["TQQQ 비율", f"{(1-TMF_RATIO)*100:.0f}% (그리드 트레이딩 풀)"],
        [""],
        ["▶ 파라미터 (최적값)"],
        ["파라미터", "값", "설명"],
        ["S (Step Size)", f"{step_pct:.1f}%", "그리드 간격 / 매수·매도 간격"],
        ["N (슬롯 수)", str(n), "TQQQ 분할 슬롯 개수"],
        ["슬롯당 크기", f"TQQQ풀 / N", f"= TQQQ풀 / {n}"],
        [""],
        ["▶ 사이클 시작 조건"],
        ["조건", "내용"],
        ["최초 시작", f"백테스트 시작일 ({START_DATE}) 기준 즉시"],
        ["이후 사이클", "직전 사이클 종료 다음 거래일 자동 시작"],
        ["ref_high", "사이클 시작 시점의 52주 최고가"],
        ["new_high_thr", "ref_high × (1 + S%) → 이 가격 도달 시 사이클 종료"],
        [""],
        ["▶ 그리드 매수 규칙"],
        ["조건", "내용"],
        ["매수 트리거", "MDD ≤ -i×S% (i = 1, 2, ..., N)"],
        ["추가 조건", "해당 슬롯(i)이 비어있을 것 + 현금 ≥ lot_size"],
        ["매수 단위", "lot_size = TQQQ풀 / N (사이클 전체 고정)"],
        ["중복 매수", "동일 슬롯은 비어있을 때만 매수 가능 (중복 불가)"],
        [""],
        ["▶ 그리드 매도 규칙"],
        ["조건", "내용"],
        ["매도 트리거", "해당 슬롯의 (매수 MDD + S%) 회복 시"],
        ["예시", "슬롯2 → -3%에서 매수 → -1.5% 이상 회복 시 매도"],
        ["슬롯 재사용", "매도 완료 즉시 슬롯 비워짐 → 가격 재하락 시 재매수 가능"],
        ["현금 복귀", "매도 수익(원금+이익) → 사이클 현금 풀로 복귀 → 재사용"],
        ["스윙 효과", "박스권 구간에서 동일 레벨 반복 매수/매도로 수익 누적"],
        [""],
        ["▶ 긴급 포지션 규칙"],
        ["단계", "조건", "액션"],
        ["긴급 #1 lot1", "N개 슬롯 동시 전부 점유 시", "TMF 1/6 매도(5%) → 매도대금으로 TQQQ 즉시 매수"],
        ["긴급 #1 lot2~6", "직전 긴급매수가 대비 -S% 추가 하락 시마다", "TMF 1/6씩 매도 → TQQQ 매수 (총 6회)"],
        ["긴급 #2 lotA", "TMF 6 Lot 전량 소진 후 직전 긴급매수가 대비 -S% 하락", "잔여 현금 절반 TQQQ 매수"],
        ["긴급 #2 lotB", "lotA 매수가 대비 -S% 추가 하락", "잔여 현금 전부 TQQQ 매수"],
        ["보유 방침", "긴급 포지션은 그리드 슬롯 전량 청산 후 사이클 종료 시 매도", ""],
        ["매도 순서", "일반 그리드 슬롯 → 긴급 lot (저점 매수 → 고점 대량 매도 구조)", ""],
        [""],
        ["▶ 가상매수 (폭락 구간 대응)"],
        ["항목", "내용", ""],
        ["발동 조건", "긴급#1(6 Lot) + 긴급#2(2 Lot) 모두 완료 후, 현금=0인 상태에서 그리드 매수 트리거 도달", ""],
        ["매수 처리", "실제 현금 없이 가상으로 포지션 진입 (현금 잔고 음수 허용 = 마진)", ""],
        ["매도 처리", "회복 시 일반 슬롯과 동일하게 전체 매도 → 전액 현금 복귀 (마진 상환 포함)", ""],
        ["목적", "폭락 최저점 부근에서 추가 매수 기회를 포착하여 반등 수익 극대화", ""],
        ["액션 표기", "Daily 탭에 VBUY-Lx로 표시 (V=Virtual)", ""],
        [""],
        ["▶ 사이클 종료 조건"],
        ["조건", "내용"],
        ["종료 트리거", f"TQQQ ≥ ref_high × (1 + S%)   ← 52주 신고가 +S% 갱신"],
        ["청산 순서", "① 긴급 포지션 전량 매도  ② 그리드 슬롯 전량 매도  ③ 남은 TMF 매도"],
        ["세금 처리", "직전 연도 실현손익에 대한 양도세 차감 후 순자산 확정"],
        ["재시작", "확정 순자산으로 즉시 새 사이클 시작 (TMF/TQQQ 리밸런싱)"],
        [""],
        ["▶ 양도세 처리"],
        ["항목", "내용"],
        ["세율", f"{TAX_RATE*100:.0f}% (지방세 포함)"],
        ["비과세 한도", f"${TAX_EXEMPTION:,.0f} / 년"],
        ["부과 기준", "연간 실현손익 합산"],
        ["납부 시점", "사이클 종료 시, 직전 해까지 미납 연도분 일괄 차감"],
        ["미완료 사이클", "사이클 종료 전 연도 세금은 다음 사이클 종료까지 이연"],
        [""],
        ["▶ 핵심 차이점 (FnG 알고리즘 vs TMF 그리드 알고리즘)"],
        ["구분", "FnG 알고리즘", "TMF 그리드 알고리즘"],
        ["매매 신호", "공포탐욕(Fear&Greed) 지수", "TQQQ 가격 레벨(MDD) 순수 기준"],
        ["매수 방식", "시그널 발생 시 분할 매수 (1회성)", "그리드 슬롯 재사용 (반복 매수/매도)"],
        ["Hold 조건", "FnG 중간 구간 시그널", "없음 (순수 가격 기준만)"],
        ["헤지 자산", "없음", "TMF 30% (채권 역상관성 활용)"],
        ["긴급 대응", "없음", "긴급#1·#2 포지션"],
    ]
    ws.update(values=data, range_name="A1", value_input_option="RAW")

    fmts = [_hdr_fmt(sid, 1, 1)]
    section_rows = [4, 12, 17, 22, 28, 35, 43, 52, 62, 73, 79]
    for r in section_rows:
        if r <= len(data):
            fmts.append(_section_fmt(sid, r, 4))
    ws.spreadsheet.batch_update({"requests": fmts})


# ── 탭 2: Summary ─────────────────────────────────────────────────────────────
def write_summary(ws, summary: dict, yearly: dict, grid: list):
    ws.clear()
    sid   = ws.id
    today = str(date.today())
    data  = [
        ["TMF + TQQQ 그리드 백테스트 결과"],
        [f"기간: {START_DATE} ~ {today}  |  초기자본: ${INITIAL_CAPITAL:,.0f}"],
        [""],
        ["▶ 최적 파라미터 결과 (CAGR 기준)"],
        ["항목", "값"],
        ["Step Size (S)",  f"{summary['step_pct']:.1f}%"],
        ["Split Count (N)", summary['n_splits']],
        ["최종 자산",       f"${summary['final_assets']:,.0f}"],
        ["총 수익률",       f"{summary['total_return_pct']:.1f}%"],
        ["CAGR",           f"{summary['cagr_pct']:.2f}%"],
        ["완료 사이클",     summary['total_cycles']],
        ["납부 세금",       f"${summary['tax_paid']:,.0f}"],
        [""],
        ["▶ 연도별 수익률 (최적 파라미터)"],
        ["연도", "시작자산($)", "종료자산($)", "수익률(%)"],
    ]
    for yr, d in sorted(yearly.items()):
        data.append([yr, round(d['start']), round(d['end']),
                     round(d['return_pct'], 2)])
    data += [
        [""],
        ["▶ 파라미터별 Top-10 (CAGR 기준)"],
        ["순위", "Step(%)", "N분할", "최종자산($)", "수익률(%)", "CAGR(%)", "사이클", "세금($)"],
    ]
    for i, r in enumerate(
            sorted(grid, key=lambda x: x['cagr_pct'], reverse=True)[:10], 1):
        data.append([i, round(r['step_pct'], 1), r['n_splits'],
                     round(r['final_assets']), round(r['total_return_pct'], 2),
                     round(r['cagr_pct'], 2), r['total_cycles'], round(r['tax_paid'])])

    ws.update(values=data, range_name="A1", value_input_option="RAW")
    hdr_rows = [1, 5, 15, len(data) - 10]
    fmts = []
    for r in [1]:
        fmts.append(_hdr_fmt(sid, r, 4))
    for r in [4, 14]:
        fmts.append(_section_fmt(sid, r, 4))
    ws.spreadsheet.batch_update({"requests": fmts})


# ── 탭 3: Cycles ─────────────────────────────────────────────────────────────
def write_cycles(ws, cycle_recs: list):
    ws.clear()
    hdrs = ["사이클", "시작일", "종료일", "시작자산($)", "종료자산($)", "수익률(%)",
            "실현손익($)", "TMF긴급Lot(0~6)", "현금긴급Lot(0~2)", "가상매수"]
    rows = [[
        c["cycle"], c["start_date"], c["end_date"],
        round(c["start_assets"]), round(c["end_assets"]),
        round(c["return_pct"], 2), round(c["realized_gains"]),
        c.get("emerg1_lots", 6 if c.get("emerg1_used") else 0),
        c.get("emerg2_lots", 2 if c.get("emerg2_used") else 0),
        "O" if c.get("virtual_used") else "",
    ] for c in cycle_recs]
    ws.update(values=[hdrs], range_name="A1", value_input_option="RAW")
    _chunks(ws, 2, rows)
    ws.spreadsheet.batch_update({"requests": [_hdr_fmt(ws.id, 1, len(hdrs))]})


# ── 탭 4: Daily ───────────────────────────────────────────────────────────────
def write_daily(ws, day_recs: List[DayRec]):
    import re as _re
    ws.clear()
    sid = ws.id

    action_rows = [r for r in day_recs if r.action != "HOLD"]
    hold_sample = [r for r in day_recs if r.action == "HOLD"][::5]
    combined    = sorted(action_rows + hold_sample, key=lambda r: r.date)

    hdrs = ["날짜", "TQQQ($)", "TMF($)", "MDD(%)", "사이클",
            "그리드슬롯", "가상슬롯", "긴급LOT", "TQQQ평가($)", "TMF평가($)", "현금($)",
            "총자산($)", "수익률(%)", "액션"]
    n_cols = len(hdrs)

    # 행 배경색 팔레트
    C_TAX     = {"red": 1.00, "green": 0.92, "blue": 0.60}  # 황금(양도세)
    C_CYCLE   = {"red": 0.84, "green": 0.94, "blue": 0.84}  # 연두(사이클 전환)
    C_VIRTUAL = {"red": 0.93, "green": 0.87, "blue": 0.98}  # 연보라(가상매수)
    C_EMERG   = {"red": 1.00, "green": 0.93, "blue": 0.80}  # 연주황(긴급)
    C_TRADE   = {"red": 0.87, "green": 0.94, "blue": 1.00}  # 연파랑(매매)

    output = []  # [(row_data, row_type), ...]

    for r in combined:
        act  = r.action
        data = [
            r.date, round(r.tqqq_price, 2), round(r.tmf_price, 2),
            round(r.mdd_pct, 2), r.cycle_num,
            r.slots_open, r.virtual_slots, r.emerg_lots_open,
            round(r.tqqq_value), round(r.tmf_value), round(r.cash),
            round(r.total_assets), round(r.total_return_pct, 2),
            act[:300],
        ]

        if "CYCLE-END" in act and "CYCLE-START" in act:
            rtype = "CYCLE"
        elif "VBUY" in act or "VSELL" in act:
            rtype = "VIRTUAL"
        elif "EMERG" in act or "ESELL" in act:
            rtype = "EMERG"
        elif "BUY" in act or "SELL" in act:
            rtype = "TRADE"
        else:
            rtype = "HOLD"

        output.append((data, rtype))

        # 사이클 전환 시 양도세 내역 별도 행 삽입
        if "CYCLE-END" in act:
            taxes = _re.findall(r'TAX-(\d+):\$(\d+)', act)
            if taxes:
                total_tax = sum(int(a) for _, a in taxes)
                desc = " | ".join(f"{yr}년 ${int(a):,}" for yr, a in taxes)
                tax_row = [
                    r.date, "", "", "", r.cycle_num,
                    "", "", "", "", "", "",
                    f"-{total_tax:,}", "",
                    f"▶ 양도세 차감: {desc}",
                ]
                output.append((tax_row, "TAX"))

    ws.update(values=[hdrs], range_name="A1", value_input_option="RAW")
    _chunks(ws, 2, [row for row, _ in output])

    color_map = {
        "CYCLE":   (C_CYCLE,   True),
        "TAX":     (C_TAX,     True),
        "VIRTUAL": (C_VIRTUAL, False),
        "EMERG":   (C_EMERG,   False),
        "TRADE":   (C_TRADE,   False),
    }
    fmt_reqs = [_hdr_fmt(sid, 1, n_cols)]
    for i, (_, rtype) in enumerate(output):
        if rtype in color_map:
            color, bold = color_map[rtype]
            fmt_reqs.append(_row_fmt(sid, i + 2, n_cols, color, bold))

    ws.spreadsheet.batch_update({"requests": fmt_reqs})


# ── 탭 5: Optimization ────────────────────────────────────────────────────────
def write_optimization(ws, grid: list):
    ws.clear()
    hdrs = ["순위", "Step(%)", "N분할", "최종자산($)", "수익률(%)", "CAGR(%)", "사이클", "세금($)"]
    rows = [[
        i + 1, round(r['step_pct'], 1), r['n_splits'],
        round(r['final_assets']), round(r['total_return_pct'], 2),
        round(r['cagr_pct'], 2), r['total_cycles'], round(r['tax_paid']),
    ] for i, r in enumerate(sorted(grid, key=lambda x: x['cagr_pct'], reverse=True))]
    ws.update(values=[hdrs], range_name="A1", value_input_option="RAW")
    _chunks(ws, 2, rows)
    ws.spreadsheet.batch_update({"requests": [_hdr_fmt(ws.id, 1, len(hdrs))]})


# ── 업로드 ────────────────────────────────────────────────────────────────────
def upload_sheets(day_recs, cycle_recs, summary, yearly, grid,
                  sheet_id: str = None) -> str:
    gc = _gc()
    if sheet_id:
        ss = gc.open_by_key(sheet_id)
        print(f"[sheets] ID로 기존 시트 열기: {sheet_id}")
    else:
        try:
            ss = gc.open(SPREADSHEET_TITLE)
            print("[sheets] 기존 스프레드시트 열기")
        except gspread.SpreadsheetNotFound:
            ss = gc.create(SPREADSHEET_TITLE)
            ss.share(USER_EMAIL, perm_type="user", role="writer")
            print(f"[sheets] 새 스프레드시트 생성 → {USER_EMAIL} 공유")

    best_step = summary['step_pct']
    best_n    = summary['n_splits']

    print("[sheets] Algorithm 탭...")
    write_algorithm(_ws(ss, "Algorithm", 100, 6), best_step, best_n)
    time.sleep(1)

    print("[sheets] Summary 탭...")
    write_summary(_ws(ss, "Summary", 200, 10), summary, yearly, grid)
    time.sleep(1)

    print("[sheets] Cycles 탭...")
    write_cycles(_ws(ss, "Cycles", max(len(cycle_recs) + 10, 200), 10), cycle_recs)
    time.sleep(1)

    print("[sheets] Daily 탭...")
    write_daily(_ws(ss, "Daily", 5000, 15), day_recs)
    time.sleep(1)

    print("[sheets] Optimization 탭...")
    write_optimization(_ws(ss, "Optimization", 200, 10), grid)

    url = f"https://docs.google.com/spreadsheets/d/{ss.id}"
    print(f"[sheets] 완료: {url}")
    return url


# ── 콘솔 출력 ─────────────────────────────────────────────────────────────────
def print_report(label: str, summary: dict, yearly: dict):
    print(f"\n{'='*55}")
    print(label)
    print(f"  초기자본: ${summary['initial_capital']:>12,.0f}")
    print(f"  최종자산: ${summary['final_assets']:>12,.0f}")
    print(f"  총수익률: {summary['total_return_pct']:>8.1f}%")
    print(f"  CAGR:    {summary['cagr_pct']:>8.2f}%")
    print(f"  사이클:  {summary['total_cycles']:>8}회")
    print(f"  납부세금: ${summary['tax_paid']:>11,.0f}")
    print(f"{'='*55}")
    print("  연도별 수익률:")
    for yr, d in sorted(yearly.items()):
        print(f"    {yr}: {d['return_pct']:>8.1f}%  →  ${d['end']:>12,.0f}")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    tqqq, tmf = load_data()

    print("\n[1/3] 파라미터 최적화 (7×7=49 조합)...")
    grid = grid_search(tqqq, tmf)
    best = max(grid, key=lambda r: r["cagr_pct"])
    print(f"\n최적: S={best['step_pct']:.1f}%  N={best['n_splits']}  "
          f"→ CAGR {best['cagr_pct']:.2f}% / 수익 {best['total_return_pct']:.0f}%")

    print(f"\n[2/3] 최적 파라미터 상세 시뮬레이션...")
    best_day, best_cycles, best_summary = simulate(
        tqqq, tmf, step=best["step_pct"] / 100, n=best["n_splits"])
    best_yearly = calc_yearly(best_day)
    print_report(f"최적 파라미터 (S={best['step_pct']:.1f}%, N={best['n_splits']})",
                 best_summary, best_yearly)

    print("\n[3/3] 기본값 (S=2.5%, N=20) 비교...")
    d_day, _, d_summary = simulate(tqqq, tmf, step=0.025, n=20)
    print_report("기본값 (S=2.5%, N=20)", d_summary, calc_yearly(d_day))

    env_cfg     = load_env_config()
    tmf_sid     = env_cfg.get("TMF_TQQQ_SPREADSHEET_ID", "").strip() or None
    print("\n구글 시트 업로드 중...")
    try:
        url = upload_sheets(best_day, best_cycles, best_summary, best_yearly, grid,
                            sheet_id=tmf_sid)
        print(f"\n구글 시트: {url}")
    except Exception as e:
        print(f"\n[경고] 구글 시트 업로드 실패: {e}")
        import traceback; traceback.print_exc()

    print("\n완료.")


if __name__ == "__main__":
    main()
