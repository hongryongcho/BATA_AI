from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STATE_FILE = Path(__file__).with_name("cycle_ppt_state.json")


def load_state(path: Path | None = None) -> dict[str, Any]:
    target = path or STATE_FILE
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any], path: Path | None = None) -> None:
    target = path or STATE_FILE
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_cycle_event_plan(ticker: str, completed_cycles: list[dict[str, Any]], open_cycle: dict[str, Any] | None, state: dict[str, Any]) -> list[str]:
    """사이클 이벤트가 새로 발생했을 때만 보고서 타입 리스트를 반환한다."""
    entry = state.get(ticker, {})
    last_completed_cycle = entry.get("last_completed_cycle")
    last_open_cycle = entry.get("last_open_cycle")

    plan: list[str] = []

    if completed_cycles:
        latest_completed = completed_cycles[-1]
        latest_completed_no = latest_completed.get("cycle_no")
        if latest_completed_no is not None and latest_completed_no != last_completed_cycle:
            plan.append("매도종료")

    if open_cycle is not None:
        open_cycle_no = open_cycle.get("cycle_no")
        if open_cycle_no is not None and open_cycle_no != last_open_cycle:
            plan.append("매수시작")

    return plan


def update_state_for_plan(ticker: str, completed_cycles: list[dict[str, Any]], open_cycle: dict[str, Any] | None, state: dict[str, Any]) -> None:
    entry = state.setdefault(ticker, {})
    if completed_cycles:
        entry["last_completed_cycle"] = completed_cycles[-1].get("cycle_no")
    if open_cycle is not None:
        entry["last_open_cycle"] = open_cycle.get("cycle_no")
