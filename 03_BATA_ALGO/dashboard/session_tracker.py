"""
방문/로그인 누적 카운터 — JSON 파일로 영구 저장
(서버 재시작해도 데이터 유지)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

ADMIN_EMAIL = "hongryong.cho@gmail.com"
_STATS_FILE = Path(__file__).parent / "visit_stats.json"
_lock = threading.Lock()

# ── 기본 데이터 구조 ─────────────────────────────────────────────
_DEFAULT: dict = {
    "total_visits": 0,       # 신규 세션(브라우저 접속) 누적
    "total_logins": 0,       # 로그인 이벤트 누적
    "login_events": [],      # [{email, timestamp}, ...]
}


def _load() -> dict:
    try:
        if _STATS_FILE.exists():
            with open(_STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 누락 키 보완
                for k, v in _DEFAULT.items():
                    data.setdefault(k, v)
                return data
    except Exception:
        pass
    return dict(_DEFAULT)


def _save(data: dict) -> None:
    try:
        with open(_STATS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ── 공개 API ─────────────────────────────────────────────────────

def record_visit() -> None:
    """새 브라우저 세션 발생 시 호출 (session_id 최초 발급 시점)"""
    with _lock:
        data = _load()
        data["total_visits"] += 1
        _save(data)


def record_login(email: str) -> None:
    """로그인 성공 시 호출"""
    with _lock:
        data = _load()
        data["total_logins"] += 1
        data["login_events"].append({
            "email": email,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        # 최대 500건 유지
        if len(data["login_events"]) > 500:
            data["login_events"] = data["login_events"][-500:]
        _save(data)


def get_stats() -> dict:
    """누적 통계 반환 (관리자 전용)"""
    with _lock:
        data = _load()

    events = data.get("login_events", [])
    unique_users = sorted(set(e["email"] for e in events))

    # 유저별 마지막 로그인
    last_by_user: dict[str, str] = {}
    for e in events:
        last_by_user[e["email"]] = e["timestamp"]

    return {
        "total_visits": data["total_visits"],
        "total_logins": data["total_logins"],
        "unique_users": unique_users,
        "unique_user_count": len(unique_users),
        "login_events": list(reversed(events)),   # 최신순
        "last_by_user": last_by_user,
    }


def is_admin(email: str | None) -> bool:
    return email == ADMIN_EMAIL
