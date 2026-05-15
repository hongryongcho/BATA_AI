"""
Google Sheets 읽기/쓰기 관리자

- [Summary] 시트에서 파라미터 읽기
- [Backtest] 시트에 결과 쓰기
- [Performance] 시트에 성과 요약 쓰기

인증: OAuth2 (기존 02_BATA_MQTT google_token.json 재사용)
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow

from _env_loader import load_env_config
from config import (
    SHEET_SUMMARY,
    SHEET_BACKTEST,
    SHEET_PERFORMANCE,
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_PATH,
    DEFAULT_PARAMS,
)
from backtest_engine import AlgoParams, DayRecord

# Google API 스코프
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# [Summary] 시트 파라미터 위치 매핑 (셀 주소 → 파라미터 키)
SUMMARY_CELL_MAP = {
    "B2": "ticker",
    "B3": "initial_capital",
    "B4": "n_splits",
    "B5": "start_date",
    "B6": "end_date",
    "B7": "base_profit_pct",
    "B8": "buy_threshold_1",
    "B9": "buy_threshold_2",
    "B10": "buy_threshold_3",
    "B11": "sell_threshold_1",
    "B12": "sell_threshold_2",
    "B13": "sell_threshold_3",
    "B14": "gap_up_pct",
    "B15": "is_3x",
}

BACKTEST_HEADERS = [
    "날짜", "종가", "52주전고점", "전고점낙폭(%)", "평단가", "평단대비수익률(%)",
    "Fear&Greed", "매매구분", "거래수량", "거래금액", "보유주식수",
    "현금잔고", "평가금액", "총자산", "수익률(%)", "사이클", "메모",
]

PERFORMANCE_LABELS = [
    ("시작일", "start_date"),
    ("종료일", "end_date"),
    ("초기자본", "initial_capital"),
    ("최종총자산", "final_total_assets"),
    ("총수익률(%)", "total_return_pct"),
    ("연평균수익률CAGR(%)", "cagr_pct"),
    ("최대낙폭MDD(%)", "mdd_pct"),
    ("총거래횟수", "total_trades"),
    ("매수횟수", "buy_count"),
    ("매도횟수", "sell_count"),
    ("총사이클수", "total_cycles"),
    ("최종현금", "final_cash"),
    ("최종보유주식수", "final_shares"),
    ("최종주식평가금액", "final_portfolio_value"),
]


class SheetsManager:

    def __init__(self, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self._gc: Optional[gspread.Client] = None

    # ── 인증 ────────────────────────────────

    def _get_client(self) -> gspread.Client:
        if self._gc is not None:
            return self._gc
        creds = self._load_or_create_credentials()
        self._gc = gspread.authorize(creds)
        return self._gc

    def _load_or_create_credentials(self):
        base_dir = Path(__file__).parent
        env = load_env_config()
        cred_rel = env.get("GOOGLE_CREDENTIALS_PATH", GOOGLE_CREDENTIALS_PATH)
        token_rel = env.get("GOOGLE_TOKEN_PATH", GOOGLE_TOKEN_PATH)
        cred_path = (base_dir / cred_rel).resolve()
        token_path = (base_dir / token_rel).resolve()

        creds = None

        if token_path.exists():
            try:
                with open(token_path, "rb") as f:
                    creds = pickle.load(f)
            except Exception:
                creds = None

        if creds and hasattr(creds, "expired") and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None

        if not creds or not creds.valid:
            if not cred_path.exists():
                raise FileNotFoundError(
                    f"Google credentials 파일 없음: {cred_path}\n"
                    "02_BATA_MQTT/config/google_credentials.json 을 확인하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
            creds = flow.run_local_server(port=0)
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
            print(f"[sheets] 새 토큰 저장: {token_path}")

        return creds

    # ── 스프레드시트 접근 ────────────────────

    def _open_spreadsheet(self):
        gc = self._get_client()
        return gc.open_by_key(self.spreadsheet_id)

    def _get_or_create_sheet(self, spreadsheet, title: str, rows=1000, cols=20):
        try:
            return spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)

    # ── [Summary] 파라미터 읽기 ──────────────

    def read_params(self) -> AlgoParams:
        print("[sheets] Summary 파라미터 읽기...")
        ss = self._open_spreadsheet()
        try:
            ws = ss.worksheet(SHEET_SUMMARY)
        except gspread.WorksheetNotFound:
            print("[sheets] Summary 시트 없음 → 기본값 사용")
            return AlgoParams()

        raw = {}
        for cell_addr, param_key in SUMMARY_CELL_MAP.items():
            try:
                val = ws.acell(cell_addr).value
                if val is not None and val != "":
                    raw[param_key] = val
            except Exception:
                pass

        params = AlgoParams.from_dict(raw)
        print(f"[sheets] 파라미터: {params.ticker} 시작={params.start_date} N={params.n_splits}")
        return params

    # ── [Backtest] 결과 쓰기 ────────────────

    def write_backtest(self, records: list[DayRecord]):
        print(f"[sheets] Backtest 시트 쓰기 ({len(records)}행)...")
        ss = self._open_spreadsheet()
        ws = self._get_or_create_sheet(ss, SHEET_BACKTEST, rows=len(records) + 10, cols=20)

        ws.clear()

        rows = [BACKTEST_HEADERS]
        for r in records:
            rows.append([
                r.date,
                r.close,
                r.high_52w,
                r.drawdown_pct,
                r.avg_cost,
                r.profit_pct,
                r.fear_greed,
                r.action,
                r.qty,
                r.trade_amount,
                r.shares,
                r.cash,
                r.portfolio_value,
                r.total_assets,
                r.return_pct,
                r.cycle,
                r.memo,
            ])

        # 배치 업데이트 (API 호출 최소화)
        ws.update(f"A1:Q{len(rows)}", rows)
        print("[sheets] Backtest 쓰기 완료")

    # ── [Performance] 성과 요약 쓰기 ────────

    def write_performance(self, summary: dict, params: AlgoParams):
        print("[sheets] Performance 시트 쓰기...")
        ss = self._open_spreadsheet()
        ws = self._get_or_create_sheet(ss, SHEET_PERFORMANCE, rows=30, cols=5)
        ws.clear()

        rows = [
            ["BATA 알고리즘 백테스트 성과 요약"],
            [f"생성시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
            [""],
            ["항목", "값"],
            ["티커", params.ticker],
            ["3배수ETF", "예" if params.is_3x else "아니오"],
            ["초기자본", params.initial_capital],
            ["등분수(N)", params.n_splits],
        ]
        for label, key in PERFORMANCE_LABELS:
            rows.append([label, summary.get(key, "")])

        ws.update(f"A1:B{len(rows)}", rows)
        # 제목 굵게 처리
        ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
        ws.format("A4:B4", {"textFormat": {"bold": True}})
        print("[sheets] Performance 쓰기 완료")

    # ── [Summary] 시트 초기 생성 ────────────

    def create_summary_template(self, params: AlgoParams = None):
        """Summary 시트가 없으면 기본 템플릿 생성"""
        if params is None:
            params = AlgoParams()
        print("[sheets] Summary 템플릿 생성...")
        ss = self._open_spreadsheet()
        ws = self._get_or_create_sheet(ss, SHEET_SUMMARY, rows=30, cols=4)
        ws.clear()

        template = [
            ["BATA 투자 알고리즘 파라미터", "", "", ""],
            ["", "", "", ""],
            ["항목", "값", "설명", "단위"],
            ["ticker", params.ticker, "대상 자산 티커", ""],
            ["initial_capital", params.initial_capital, "초기 투자 자본", "USD"],
            ["n_splits", params.n_splits, "등분 수 (단위수량 = 자본/N/가격)", "정수"],
            ["start_date", params.start_date, "백테스트 시작일", "YYYY-MM-DD"],
            ["end_date", params.end_date or "", "백테스트 종료일 (빈칸=오늘)", "YYYY-MM-DD"],
            ["base_profit_pct", params.base_profit_pct, "기본 매도 수익 기준 (3배수는 자동×3)", "%"],
            ["buy_threshold_1", 10.0, "2배수 매수 낙폭 기준", "%"],
            ["buy_threshold_2", 15.0, "3배수 매수 낙폭 기준", "%"],
            ["buy_threshold_3", 20.0, "4배수 매수 낙폭 기준", "%"],
            ["sell_threshold_1", 10.0, "2배수 매도 수익 기준", "%"],
            ["sell_threshold_2", 20.0, "3배수 매도 수익 기준", "%"],
            ["sell_threshold_3", 30.0, "4배수 매도 수익 기준", "%"],
            ["gap_up_pct", 2.0, "갭업 강제매도 기준 (3배수는 자동×3)", "%"],
            ["is_3x", "FALSE", "3배수 ETF 여부 (TRUE/FALSE, 빈칸=자동감지)", ""],
        ]

        # B열에 파라미터 값 (B2=ticker 등)이 SUMMARY_CELL_MAP 과 맞도록 재배치
        # 이 템플릿은 A열=설명, B열=값 구조로 맞춤
        summary_rows = [["BATA 알고리즘 파라미터 (Summary)"], [""]]
        label_map = {
            "ticker": "대상 자산 티커",
            "initial_capital": "초기자본 (USD)",
            "n_splits": "등분수(N)",
            "start_date": "백테스트 시작일",
            "end_date": "백테스트 종료일 (빈칸=오늘)",
            "base_profit_pct": "기본수익기준(%)",
            "buy_threshold_1": "매수2배수낙폭(%)",
            "buy_threshold_2": "매수3배수낙폭(%)",
            "buy_threshold_3": "매수4배수낙폭(%)",
            "sell_threshold_1": "매도2배수수익(%)",
            "sell_threshold_2": "매도3배수수익(%)",
            "sell_threshold_3": "매도4배수수익(%)",
            "gap_up_pct": "갭업강제매도기준(%)",
            "is_3x": "3배수ETF여부(TRUE/FALSE)",
        }
        default_values = {
            "ticker": params.ticker,
            "initial_capital": params.initial_capital,
            "n_splits": params.n_splits,
            "start_date": params.start_date,
            "end_date": params.end_date or "",
            "base_profit_pct": 3.0,
            "buy_threshold_1": 10.0,
            "buy_threshold_2": 15.0,
            "buy_threshold_3": 20.0,
            "sell_threshold_1": 10.0,
            "sell_threshold_2": 20.0,
            "sell_threshold_3": 30.0,
            "gap_up_pct": 2.0,
            "is_3x": "FALSE",
        }

        # B열 = 값 (SUMMARY_CELL_MAP 기준 B2~B15)
        for key, label in label_map.items():
            summary_rows.append([label, default_values[key]])

        ws.update(f"A1:B{len(summary_rows)}", summary_rows)
        ws.format("A1", {"textFormat": {"bold": True, "fontSize": 14}})
        ws.format("A3:A{len(summary_rows)}", {"textFormat": {"bold": True}})
        print("[sheets] Summary 템플릿 생성 완료")
