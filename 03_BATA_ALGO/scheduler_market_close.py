"""
BATA_RSI2_FnG_ALGO 자동 업데이트 스케줄러
────────────────────────────────────────────
RSI2+FnG 알고리즘 고정 실행
  ├─ 프리장(04:00 ET): 현재값 기준 시뮬레이션
  └─ 장마감(16:30 ET): 종가 기준 시뮬레이션 [종가로 재계산]

실행 방법 1 ─ 상시 데몬 (권장 / 자동 DST 대응):
    python3 scheduler_market_close.py --daemon

실행 방법 2 ─ cron 등록 (선택사항):
    python3 scheduler_market_close.py --install-cron

실행 방법 3 ─ 단 1회 즉시 실행:
    python3 scheduler_market_close.py --once
    python3 scheduler_market_close.py --premarket-once

Daemon 실행 (백그라운드):
    python3 scheduler_market_close.py --daemon > logs/scheduler.log 2>&1 &

데몬 프로세스 확인:
    ps aux | grep scheduler_market_close.py
    ps aux | grep personal_bot.py

데몬 종료:
    pkill -f scheduler_market_close
    pkill -f personal_bot
"""

from __future__ import annotations

import argparse
import json
import os
import concurrent.futures
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo   # Python 3.9+

import pandas as pd
import yfinance as yf

from _env_loader import get_spreadsheet_id, get_qqq_guard_spreadsheet_id, load_env_config
from sheets_manager import SheetsManager

SCRIPT_DIR = Path(__file__).parent.resolve()
TARGET_SCRIPTS = [
    SCRIPT_DIR / "create_qqq_guard_daily.py",
]
LOG_FILE = SCRIPT_DIR / "logs" / "scheduler_fng.log"
CRON_MARKER = "# BATA_FNG_ONLY"

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def _read_simple_env_file(env_path: Path) -> dict:
    data = {}
    if not env_path.exists():
        return data
    for line in env_path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        data[k.strip()] = v.strip()
    return data


def _log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _run_targets(dry_run: bool = False, send_close_message: bool = True):
    sheet_link = ""
    for target_script in TARGET_SCRIPTS:
        _log(f"▶ 실행 시작: {target_script.name}")
        try:
            result = subprocess.run(
                [sys.executable, str(target_script)],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=900,
            )
            if result.returncode == 0:
                tail = "\n".join(result.stdout.strip().splitlines()[-8:])
                _log(f"✅ 완료: {target_script.name}\n{tail}")
                
                # 시트 링크 추출 (구글 시트 링크 형식)
                for line in result.stdout.splitlines():
                    if "https://docs.google.com/spreadsheets/d/" in line:
                        sheet_link = line.split("https://")[-1]
                        sheet_link = "https://" + sheet_link
                        break
            else:
                _log(f"❌ 오류 ({target_script.name}, exit {result.returncode})\n{result.stderr[-800:]}")
                return ""  # 시트 업데이트 실패 시 텔레그램 전송 생략
        except subprocess.TimeoutExpired:
            _log(f"❌ 타임아웃: {target_script.name} (900초 초과)")
            return ""
        except Exception as e:
            _log(f"❌ 예외 발생: {target_script.name} | {e}")
            return ""

    # 시트 업데이트 완료 후 장마감 텔레그램 알림 전송
    if send_close_message:
        try:
            send_market_close_action_to_telegram(sheet_link=sheet_link, dry_run=dry_run)
        except Exception as e:
            _log(f"⚠️ 장마감 텔레그램 전송 실패: {e}")

    return sheet_link


def _next_run_time() -> datetime:
    """다음 장 마감 +15분(ET 기준 16:15) 시각 계산 [종가 기준]"""
    now_et = datetime.now(ET)
    target = now_et.replace(hour=16, minute=15, second=0, microsecond=0)

    # 오늘 16:15 가 이미 지났으면 다음 영업일
    if now_et >= target:
        target += timedelta(days=1)

    # 주말 건너뜀
    while target.weekday() >= 5:   # 5=토, 6=일
        target += timedelta(days=1)

    return target


def _is_market_close_plus_15_now(tolerance_min: int = 3) -> bool:
    """현재 ET 시각이 장 마감+15분(16:15) ~ 23:59 사이인지 판별"""
    now_et = datetime.now(ET)
    target_start = now_et.replace(hour=16, minute=15, second=0, microsecond=0)
    target_end = now_et.replace(hour=23, minute=59, second=59, microsecond=0)

    # 실행 가능 시간대 확인
    return target_start <= now_et <= target_end


def _is_premarket_open_now(tolerance_min: int = 3) -> bool:
    """현재 ET 시각이 프리장 오픈(04:00) 근처인지 판별"""
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    target = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
    delta_min = abs((now_et - target).total_seconds()) / 60.0
    return delta_min <= tolerance_min


def _is_us_trading_day(today_et: datetime) -> bool:
    """미국 실거래일 여부 확인 (주말 + NYSE 휴장일 필터)."""
    if today_et.weekday() >= 5:
        return False

    # yfinance 일봉에 오늘 날짜가 있으면 거래일로 판단
    try:
        probe = yf.download(
            "SPY",
            period="10d",
            interval="1d",
            progress=False,
            auto_adjust=False,
            threads=False,
        )
        if probe is None or probe.empty:
            _log("⚠️ 거래일 판별 데이터 없음(yfinance) → 보수적으로 스킵")
            return False

        idx_dates = set(pd.to_datetime(probe.index).date)
        return today_et.date() in idx_dates
    except Exception as e:
        _log(f"⚠️ 거래일 판별 실패: {e} → 보수적으로 스킵")
        return False


def _resolve_telegram_config() -> tuple[str, str]:
    """FnG 전용 텔레그램 전송 대상 조회 (전용 설정 우선)."""
    env = load_env_config()
    mqtt_env = _read_simple_env_file(SCRIPT_DIR.parent / "02_BATA_MQTT" / ".env")

    # 우선순위: FnG 전용 > 기존 major/general
    token = (
        os.getenv("TELEGRAM_FNG_BOT_TOKEN")
        or env.get("TELEGRAM_FNG_BOT_TOKEN", "")
        or mqtt_env.get("TELEGRAM_FNG_BOT_TOKEN", "")
        or os.getenv("TELEGRAM_MAJOR_BOT_TOKEN")
        or os.getenv("TELEGRAM_BOT_TOKEN")
        or env.get("TELEGRAM_MAJOR_BOT_TOKEN", "")
        or env.get("TELEGRAM_BOT_TOKEN", "")
        or mqtt_env.get("TELEGRAM_MAJOR_BOT_TOKEN", "")
        or mqtt_env.get("TELEGRAM_BOT_TOKEN", "")
    )
    chat_id = (
        os.getenv("TELEGRAM_FNG_CHAT_ID")
        or env.get("TELEGRAM_FNG_CHAT_ID", "")
        or mqtt_env.get("TELEGRAM_FNG_CHAT_ID", "")
        or os.getenv("TELEGRAM_MAJOR_CHAT_ID")
        or os.getenv("TELEGRAM_NOTIFY_CHAT_ID")
        or os.getenv("TELEGRAM_CHAT_ID")
        or os.getenv("TELEGRAM_ALLOWED_CHAT_ID")
        or env.get("TELEGRAM_MAJOR_CHAT_ID", "")
        or env.get("TELEGRAM_NOTIFY_CHAT_ID", "")
        or env.get("TELEGRAM_CHAT_ID", "")
        or env.get("TELEGRAM_ALLOWED_CHAT_ID", "")
        or mqtt_env.get("TELEGRAM_MAJOR_CHAT_ID", "")
        or mqtt_env.get("TELEGRAM_NOTIFY_CHAT_ID", "")
        or mqtt_env.get("TELEGRAM_CHAT_ID", "")
        or mqtt_env.get("TELEGRAM_ALLOWED_CHAT_ID", "")
    )
    return token, chat_id


SHEETS_READ_TIMEOUT_SEC = 60  # gspread 조회 최대 대기 시간


def _read_fng_action_rows() -> list[dict]:
    """Summary 탭에서 현재 사이클/추천 예약주문 블록 읽기 (timeout 적용)"""
    def _fetch():
        spreadsheet_id = get_qqq_guard_spreadsheet_id()
        sm = SheetsManager(spreadsheet_id=spreadsheet_id)
        gc = sm._get_client()
        ss = gc.open_by_key(spreadsheet_id)
        ws = ss.worksheet("Summary")
        return ws.get_all_values()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_fetch)
        try:
            values = future.result(timeout=SHEETS_READ_TIMEOUT_SEC)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Google Sheets 조회 {SHEETS_READ_TIMEOUT_SEC}초 초과 (네트워크 문제)")

    section_title = "[ 현재 사이클 & 다음날 예약 주문 (RSI2+F&G+QQQ가드 기준) ]"
    section_idx = None
    for i, row in enumerate(values):
        if row and row[0].strip() == section_title:
            section_idx = i
            break

    if section_idx is None:
        raise ValueError("Summary 탭에서 현재 사이클 섹션을 찾지 못했습니다.")

    data_start = section_idx + 2
    rows: list[dict] = []
    for r in values[data_start:]:
        if not r or not r[0].strip():
            break
        ticker = r[0].strip()
        if ticker not in {"TQQQ", "SOXL"}:
            continue
        rows.append(
            {
                "ticker": ticker,
                "strategy": r[1].strip() if len(r) > 1 else "",
                "current_state": r[2].strip() if len(r) > 2 else "",
                "next_action": r[9].strip() if len(r) > 9 else "",
            }
        )

    if not rows:
        raise ValueError("Summary 탭에서 TQQQ/SOXL 주문 행을 찾지 못했습니다.")
    return rows


def _build_market_close_message(action_rows: list[dict], sheet_link: str = "") -> str:
    """장마감 +15분 알림 메시지 (당일 마감 데이터 기준)"""
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    try:
        from fear_greed import fetch_fear_greed
        fng = fetch_fear_greed()
        fng_value = fng["value"]
        fng_desc = _get_fng_emoji(fng_value)
        fng_source = fng["source"].upper()
        fng_line = f"😨 Fear & Greed: {fng_value}/100  {fng_desc}  [{fng_source}]"
    except Exception as e:
        fng_line = f"😨 Fear & Greed: 조회 실패 ({e})"

    lines = [
        "[ FnG 투자 알림 - 미국 장마감 (오늘 마감 데이터) ]",
        f"⏰ {now_et}  /  {now_kst} KST",
        fng_line,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for row in action_rows:
        action = row["next_action"]
        if "BUY" in action.upper():
            signal_emoji = "🟢"
        elif "SELL" in action.upper():
            signal_emoji = "🔴"
        else:
            signal_emoji = "⏸"
        lines.append(f"{signal_emoji} {row['ticker']}  |  {row['strategy']}  |  {row['current_state']}")
        lines.append(f"   📌 {action}")
        lines.append("")

    # 구글시트 링크 추가
    if sheet_link:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 백테스트 결과: {sheet_link}")
        lines.append("   💡 링크 열기: 백테스트 결과 열람 (읽기 전용)")
        lines.append("   💾 편집: 사본 생성해서 수정 가능")

    lines.append("")
    lines.append("📋 내일 프리장(04:00 ET) 에 현재값 기준 최종 알림을 보냅니다.")
    return "\n".join(lines).strip()


def send_market_close_action_to_telegram(sheet_link: str = "", dry_run: bool = False):
    """장마감 +15분 텔레그램 알림 전송"""
    rows = _read_fng_action_rows()
    msg = _build_market_close_message(rows, sheet_link=sheet_link)
    token, chat_id = _resolve_telegram_config()

    if dry_run:
        _log("🧪 장마감 텔레그램 미리보기 (dry-run)")
        _log(msg)
        return

    result = _send_telegram_message(msg, token, chat_id)
    msg_id = result.get("result", {}).get("message_id")
    _log(f"✅ 장마감 액션 텔레그램 전송 완료 (chat_id={chat_id}, message_id={msg_id})")


def _get_fng_emoji(value: int) -> str:
    if value <= 24:
        return "😱 Extreme Fear"
    elif value <= 44:
        return "😟 Fear"
    elif value <= 54:
        return "😐 Neutral"
    elif value <= 74:
        return "🤑 Greed"
    else:
        return "🚀 Extreme Greed"


def _build_premarket_message(action_rows: list[dict], sheet_link: str = "") -> str:
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")

    # CNN Fear & Greed 실시간 조회
    try:
        from fear_greed import fetch_fear_greed
        fng = fetch_fear_greed()
        fng_value = fng["value"]
        fng_desc = _get_fng_emoji(fng_value)
        fng_source = fng["source"].upper()
        fng_line = f"😨 Fear & Greed: {fng_value}/100  {fng_desc}  [{fng_source}]"
    except Exception as e:
        fng_line = f"😨 Fear & Greed: 조회 실패 ({e})"

    lines = [
        "[ FnG 투자 알림 - 미국 프리장 오픈 (현재값 기준) ]",
        f"⏰ {now_et}  /  {now_kst} KST",
        fng_line,
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for row in action_rows:
        action = row["next_action"]
        # 신호에 따른 이모지
        if "BUY" in action.upper():
            signal_emoji = "🟢"
        elif "SELL" in action.upper():
            signal_emoji = "🔴"
        else:
            signal_emoji = "⏸"
        lines.append(f"{signal_emoji} {row['ticker']}  |  {row['strategy']}  |  {row['current_state']}")
        lines.append(f"   📌 {action}")
        lines.append("")

    # 구글시트 링크 추가 (프리장용)
    if sheet_link:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📊 백테스트 결과: {sheet_link}")
        lines.append("   💡 링크 열기: 백테스트 결과 열람 (읽기 전용)")
        lines.append("   💾 편집: 사본 생성해서 수정 가능")

    return "\n".join(lines).strip()


def _send_telegram_message(text: str, token: str, chat_id: str):
    if not token or not chat_id:
        raise ValueError("텔레그램 토큰/챗ID가 비어 있습니다.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        if not data.get("ok"):
            raise RuntimeError(f"텔레그램 전송 실패: {data}")
        return data


def send_premarket_action_to_telegram(sheet_link: str = "", dry_run: bool = False):
    rows = _read_fng_action_rows()
    msg = _build_premarket_message(rows, sheet_link=sheet_link)
    token, chat_id = _resolve_telegram_config()

    if dry_run:
        _log("🧪 프리장 텔레그램 미리보기 (dry-run)")
        _log(msg)
        return

    result = _send_telegram_message(msg, token, chat_id)
    msg_id = result.get("result", {}).get("message_id")
    _log(f"✅ 프리장 액션 텔레그램 전송 완료 (chat_id={chat_id}, message_id={msg_id})")


def _next_premarket_time() -> datetime:
    """다음 프리장 오픈(ET 기준 04:00) 시각 계산"""
    now_et = datetime.now(ET)
    target = now_et.replace(hour=4, minute=0, second=0, microsecond=0)
    if now_et >= target:
        target += timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target


def daemon_loop():
    _log("🟢 FnG 스케줄러 데몬 시작 (RSI2+FnG+QQQ가드 알고리즘)")
    _log("   ├─ 04:00 ET: 프리장 오픈 - 현재값 기준 시뮬레이션 + 업데이트")
    _log("   ├─ 16:15 ET: 장마감 후 15분 - 종가 기준 시뮬레이션 + 업데이트")
    _log("   └─ 텔레그램 자동 알림 (FnG+QQQ가드 봇 동시 실행)")
    premarket_sent_today: str = ""
    close_sent_today: str = ""
    last_sheet_link: str = ""  # 마지막 생성된 시트 링크 캐시

    while True:
        now_et = datetime.now(ET)
        today_str = now_et.strftime("%Y-%m-%d")

        # ── 프리장 오픈(04:00 ET) 시트 업데이트 + 알림 ──
        if (
            _is_premarket_open_now()
            and now_et.weekday() < 5
            and premarket_sent_today != today_str
        ):
            _log(f"🌅 프리장 오픈 실행 ({now_et.strftime('%H:%M ET')})")
            premarket_sent_today = today_str  # 실패해도 중복 실행 방지
            try:
                last_sheet_link = _run_targets(dry_run=False, send_close_message=False)
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    f = ex.submit(send_premarket_action_to_telegram, last_sheet_link)
                    f.result(timeout=120)
            except concurrent.futures.TimeoutError:
                _log("⚠️ 프리장 텔레그램 전송 120초 초과 (네트워크 문제)")
            except Exception as e:
                _log(f"⚠️ 프리장 실행 실패: {e}")

        # ── 장마감+15분(16:30 ET) 시트 업데이트 + 알림 ──
        if (
            _is_market_close_plus_15_now()
            and close_sent_today != today_str
        ):
            close_sent_today = today_str  # 실패해도 중복 실행 방지
            if _is_us_trading_day(now_et):
                _log(f"🔔 장마감+15분 실행 ({now_et.strftime('%H:%M ET')})")
                last_sheet_link = _run_targets()  # 시트 업데이트 + 텔레그램 자동 전송, 링크 저장
            else:
                _log(f"⏭ 스킵: 미국 비거래일({now_et.strftime('%Y-%m-%d ET')})")

        time.sleep(30)  # 30초마다 체크


def install_cron():
    """crontab 항목 추가 (DST/표준시 자동 대응)"""
    python = sys.executable
    close_cmd = f"{python} {SCRIPT_DIR / 'scheduler_market_close.py'} --once >> {LOG_FILE} 2>&1"
    pre_cmd = f"{python} {SCRIPT_DIR / 'scheduler_market_close.py'} --premarket-once >> {LOG_FILE} 2>&1"

    # ET 16:15 (장마감+15분 종가 기준): DST=KST 다음날 05:15, 표준시=KST 다음날 06:15
    # ET 16:15 EDT(UTC-4) = UTC 20:15 = KST 05:15 (다음날) → 화~토 05:15
    # ET 16:15 EST(UTC-5) = UTC 21:15 = KST 06:15 (다음날) → 화~토 06:15
    close_cron_dst = f"15 5 * * 2-6 {close_cmd} {CRON_MARKER}"
    close_cron_std = f"15 6 * * 2-6 {close_cmd} {CRON_MARKER}"

    # ET 04:00 (프리장 오픈): DST=KST 17:00, 표준시=KST 18:00
    # ET 04:00 EDT(UTC-4) = UTC 08:00 = KST 17:00
    # ET 04:00 EST(UTC-5) = UTC 09:00 = KST 18:00
    pre_cron_dst = f"0 17 * * 1-5 {pre_cmd} {CRON_MARKER}"
    pre_cron_std = f"0 18 * * 1-5 {pre_cmd} {CRON_MARKER}"

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    # 기존 단일 실행 엔트리 및 이전 마커 엔트리 제거 후 갱신
    filtered_lines = []
    for line in existing.splitlines():
        if CRON_MARKER in line:
            continue
        if "create_rsi_price_target_sheet.py" in line:
            continue
        if "create_rsi_fng_sheet.py" in line:
            continue
        filtered_lines.append(line)

    new_crontab = "\n".join(filtered_lines).rstrip("\n") + (
        f"\n{close_cron_dst}\n{close_cron_std}\n{pre_cron_dst}\n{pre_cron_std}\n"
    )
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
    if proc.returncode == 0:
        print("✅ cron 등록/갱신 완료 (DST 자동 대응)")
        print(f"   {close_cron_dst}")
        print(f"   {close_cron_std}")
        print(f"   {pre_cron_dst}")
        print(f"   {pre_cron_std}")
        print("\nℹ️  --once 는 ET 16:30±3분, --premarket-once 는 ET 04:00±3분에서만 실제 실행됩니다.")
    else:
        print("❌ cron 등록 실패")


def main():
    parser = argparse.ArgumentParser(description="BATA RSI2 / RSI2+FnG 자동 업데이트 스케줄러")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daemon",       action="store_true", help="상시 데몬으로 실행 (권장)")
    group.add_argument("--once",         action="store_true", help="즉시 1회 실행")
    group.add_argument("--premarket-once", action="store_true", help="프리장 오픈(04:00 ET) 알림 1회 전송")
    group.add_argument("--install-cron", action="store_true", help="crontab 에 등록")
    parser.add_argument("--force", action="store_true", help="시간 조건 무시하고 강제 실행")
    parser.add_argument("--dry-run", action="store_true", help="텔레그램 전송 없이 미리보기 로그만 출력")
    args = parser.parse_args()

    if args.once:
        if args.force:
            _log("⚡ 장마감 종가 데이터 기준 업데이트 (강제 실행)")
            _run_targets(dry_run=args.dry_run)
        elif _is_market_close_plus_15_now():
            now_et = datetime.now(ET)
            if _is_us_trading_day(now_et):
                _log("⚡ 장마감 종가 데이터 기준 업데이트 (16:30 ET)")
                _run_targets(dry_run=args.dry_run)
            else:
                _log(f"⏭ 스킵: 미국 비거래일({now_et.strftime('%Y-%m-%d ET')})")
        else:
            now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
            _log(f"⏭ 스킵: 현재 시각({now_et})은 장마감+15분(16:30 ET) 실행 윈도우가 아님")
    elif args.premarket_once:
        if args.force:
            _log("⚡ 프리장 현재값 기준 업데이트 (강제 실행)")
            link = _run_targets(dry_run=args.dry_run, send_close_message=False)
            send_premarket_action_to_telegram(sheet_link=link, dry_run=args.dry_run)
        elif _is_premarket_open_now():
            now_et = datetime.now(ET)
            if now_et.weekday() < 5:
                _log("⚡ 프리장 현재값 기준 업데이트 (04:00 ET)")
                link = _run_targets(dry_run=args.dry_run, send_close_message=False)
                send_premarket_action_to_telegram(sheet_link=link, dry_run=args.dry_run)
            else:
                _log(f"⏭ 스킵: 주말({now_et.strftime('%Y-%m-%d ET')})")
        else:
            now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
            _log(f"⏭ 스킵: 현재 시각({now_et})은 프리장 오픈(04:00 ET) 실행 윈도우가 아님")
    elif args.install_cron:
        install_cron()
    else:
        daemon_loop()


if __name__ == "__main__":
    main()
