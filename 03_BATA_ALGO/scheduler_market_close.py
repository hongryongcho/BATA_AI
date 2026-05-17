"""
BATA_RSI2_FnG_ALGO 자동 업데이트 스케줄러
────────────────────────────────────────────
미국 장 마감(4:00 PM ET) + 15분 후(4:15 PM ET)에
create_rsi_fng_sheet.py 를 실행.

실행 방법 1 ─ cron 등록 (권장):
    python3 scheduler_market_close.py --install-cron

실행 방법 2 ─ 상시 데몬 (직접 루프):
    python3 scheduler_market_close.py --daemon

실행 방법 3 ─ 단 1회 즉시 실행:
    python3 scheduler_market_close.py --once

cron 등록 내용 (ET 기준 4:15 PM = UTC 20:15):
    15 20 * * 1-5  ...  (월~금, UTC)
    ※ 서머타임 적용 기간(3월~11월)은 19:15 UTC → 연중 자동 처리하려면 데몬 모드 사용
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo   # Python 3.9+

import pandas as pd
import yfinance as yf

SCRIPT_DIR = Path(__file__).parent.resolve()
TARGET_SCRIPTS = [
    SCRIPT_DIR / "create_rsi_fng_sheet.py",
]
LOG_FILE = SCRIPT_DIR / "logs" / "scheduler_fng.log"
CRON_MARKER = "# BATA_FNG_ONLY"

ET = ZoneInfo("America/New_York")


def _log(msg: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def _run_targets():
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
                # 마지막 8줄만 로그
                tail = "\n".join(result.stdout.strip().splitlines()[-8:])
                _log(f"✅ 완료: {target_script.name}\n{tail}")
            else:
                _log(f"❌ 오류 ({target_script.name}, exit {result.returncode})\n{result.stderr[-800:]}")
        except subprocess.TimeoutExpired:
            _log(f"❌ 타임아웃: {target_script.name} (900초 초과)")
        except Exception as e:
            _log(f"❌ 예외 발생: {target_script.name} | {e}")


def _next_run_time() -> datetime:
    """다음 장 마감 +15분(ET 기준 16:15) 시각 계산"""
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
    """현재 ET 시각이 장 마감+15분(16:15) 근처인지 판별"""
    now_et = datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    target = now_et.replace(hour=16, minute=15, second=0, microsecond=0)
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


def daemon_loop():
    _log("🟢 BATA_RSI2_ALGO + BATA_RSI2_FnG_ALGO 스케줄러 데몬 시작")
    while True:
        next_run = _next_run_time()
        wait_sec = (next_run - datetime.now(ET)).total_seconds()
        _log(f"⏳ 다음 실행: {next_run.strftime('%Y-%m-%d %H:%M ET')} (대기 {wait_sec/3600:.1f}h)")
        time.sleep(max(wait_sec, 0))
        now_et = datetime.now(ET)
        if _is_us_trading_day(now_et):
            _run_targets()
        else:
            _log(f"⏭ 스킵: 미국 비거래일({now_et.strftime('%Y-%m-%d ET')})")
        time.sleep(60)   # 이중 실행 방지


def install_cron():
    """crontab 에 항목 추가 (DST 대응: UTC 20:15 + 21:15 월~금)"""
    python = sys.executable
    cmd = f"{python} {SCRIPT_DIR / 'scheduler_market_close.py'} --once >> {LOG_FILE} 2>&1"
    cron_line_dst = f"15 20 * * 1-5 {cmd} {CRON_MARKER}"
    cron_line_std = f"15 21 * * 1-5 {cmd} {CRON_MARKER}"

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

    new_crontab = "\n".join(filtered_lines).rstrip("\n") + f"\n{cron_line_dst}\n{cron_line_std}\n"
    proc = subprocess.run(["crontab", "-"], input=new_crontab, text=True)
    if proc.returncode == 0:
        print("✅ cron 등록/갱신 완료 (DST 자동 대응)")
        print(f"   {cron_line_dst}")
        print(f"   {cron_line_std}")
        print("\nℹ️  스크립트가 ET 16:15(±3분)일 때만 실제 실행하며, 나머지는 자동 스킵합니다.")
    else:
        print("❌ cron 등록 실패")


def main():
    parser = argparse.ArgumentParser(description="BATA RSI2 / RSI2+FnG 자동 업데이트 스케줄러")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daemon",       action="store_true", help="상시 데몬으로 실행 (권장)")
    group.add_argument("--once",         action="store_true", help="즉시 1회 실행")
    group.add_argument("--install-cron", action="store_true", help="crontab 에 등록")
    parser.add_argument("--force", action="store_true", help="시간 조건 무시하고 강제 실행")
    args = parser.parse_args()

    if args.once:
        if args.force:
            _run_targets()
        elif _is_market_close_plus_15_now():
            now_et = datetime.now(ET)
            if _is_us_trading_day(now_et):
                _run_targets()
            else:
                _log(f"⏭ 스킵: 미국 비거래일({now_et.strftime('%Y-%m-%d ET')})")
        else:
            now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S ET")
            _log(f"⏭ 스킵: 현재 시각({now_et})은 장마감+15분(16:15 ET) 실행 윈도우가 아님")
    elif args.install_cron:
        install_cron()
    else:
        daemon_loop()


if __name__ == "__main__":
    main()
