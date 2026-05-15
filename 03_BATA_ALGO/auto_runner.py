"""
Google Sheets 파라미터 변경 자동 감지 러너

동작 방식:
- Summary 시트 파라미터를 주기적으로 읽음
- 이전 상태와 다르면 run_backtest.py를 자동 실행
- 최초 실행 시에는 상태 파일이 없으면 1회 자동 실행

실행 예시:
  python3 auto_runner.py --interval-sec 60
  python3 auto_runner.py --once
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

from _env_loader import get_spreadsheet_id
from sheets_manager import SheetsManager

STATE_FILE = Path(__file__).parent / ".auto_runner_state.json"


def parse_args():
    parser = argparse.ArgumentParser(description="BATA 자동 백테스트 러너")
    parser.add_argument(
        "--interval-sec",
        type=int,
        default=60,
        help="파라미터 변경 감지 주기(초), 기본 60",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="1회만 체크하고 종료",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="변경 여부와 무관하게 즉시 1회 실행",
    )
    return parser.parse_args()


def build_params_signature(sm: SheetsManager) -> str:
    params = sm.read_params()
    payload = {
        "ticker": params.ticker,
        "initial_capital": params.initial_capital,
        "n_splits": params.n_splits,
        "start_date": params.start_date,
        "end_date": params.end_date,
        "base_profit_pct": params.base_profit_pct,
        "buy_threshold_1": params.buy_threshold_1,
        "buy_threshold_2": params.buy_threshold_2,
        "buy_threshold_3": params.buy_threshold_3,
        "sell_threshold_1": params.sell_threshold_1,
        "sell_threshold_2": params.sell_threshold_2,
        "sell_threshold_3": params.sell_threshold_3,
        "gap_up_pct": params.gap_up_pct,
        "is_3x": params.is_3x,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(signature: str):
    data = {
        "last_signature": signature,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def run_backtest_command() -> int:
    cmd = ["python3", "run_backtest.py"]
    print(f"[auto] 실행: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=Path(__file__).parent)
    return proc.returncode


def check_and_run(sm: SheetsManager, force: bool = False) -> bool:
    state = load_state()
    old_sig = state.get("last_signature")
    new_sig = build_params_signature(sm)

    changed = (old_sig != new_sig)
    if force:
        changed = True

    if changed:
        reason = "강제실행" if force else ("초기실행" if not old_sig else "파라미터변경")
        print(f"[auto] 변경 감지 → 백테스트 실행 ({reason})")
        code = run_backtest_command()
        if code == 0:
            save_state(new_sig)
            print("[auto] 실행 성공, 상태 갱신 완료")
            return True
        print(f"[auto] 실행 실패 (exit={code})")
        return False

    print("[auto] 변경 없음")
    return True


def main():
    args = parse_args()
    sheet_id = get_spreadsheet_id()
    sm = SheetsManager(spreadsheet_id=sheet_id)

    print("=" * 60)
    print("BATA 자동 백테스트 러너")
    print("=" * 60)
    print(f"[auto] sheet_id: {sheet_id}")
    print(f"[auto] 주기: {args.interval_sec}초")

    if args.once:
        ok = check_and_run(sm=sm, force=args.force)
        raise SystemExit(0 if ok else 1)

    # 데몬 루프
    first = True
    while True:
        try:
            ok = check_and_run(sm=sm, force=(args.force and first))
            first = False
            if not ok:
                print("[auto] 다음 주기에 재시도")
        except KeyboardInterrupt:
            print("\n[auto] 종료")
            break
        except Exception as e:
            print(f"[auto] 오류: {e}")

        time.sleep(max(args.interval_sec, 10))


if __name__ == "__main__":
    main()
