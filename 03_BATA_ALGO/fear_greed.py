"""
Fear & Greed 지수 조회
CNN 전용, 오늘 날짜 캐시 → 실패 시 중앙값 50(중립) 폴백
"""

import json
import urllib.request
from datetime import date
from pathlib import Path
from typing import Optional
from config import FEAR_GREED_URL, FEAR_GREED_ALT_URL, EXTREME_FEAR_MAX, EXTREME_GREED_MIN

_DAILY_CACHE_FILE = Path(__file__).parent / "cache" / "fng" / "fng_daily_cache.json"


def fetch_fear_greed() -> dict:
    """
    Returns:
        {"value": int, "label": str, "source": str}
        또는 실패: {"value": 50, "label": "중립", "source": "fallback", "error": True}

    CNN 전용. 오늘 날짜 캐시가 있으면 재사용.
    실패 시 중앙값 50(중립)으로 대체하되 error=True 플래그를 함께 반환.
    대체 중임을 UI에서 반드시 표시해야 함.
    """
    cached = _load_today_cache()
    if cached is not None:
        return cached

    result = _fetch_from_cnn()
    if result is not None:
        _save_today_cache(result)
        return result

    return {"value": 50, "label": "중립", "source": "fallback", "error": True}


def _load_today_cache() -> Optional[dict]:
    try:
        if not _DAILY_CACHE_FILE.exists():
            return None
        data = json.loads(_DAILY_CACHE_FILE.read_text(encoding="utf-8"))
        if data.get("date") == date.today().isoformat():
            return {"value": data["value"], "label": data["label"], "source": "cache"}
    except Exception:
        pass
    return None


def _save_today_cache(result: dict) -> None:
    try:
        _DAILY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": date.today().isoformat(),
            "value": result["value"],
            "label": result["label"],
        }
        _DAILY_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


_LABEL_KO: dict[str, str] = {
    "extreme fear": "극도 공포",
    "fear": "공포",
    "neutral": "중립",
    "greed": "탐욕",
    "extreme greed": "극도 탐욕",
}


def _to_korean_label(label: str) -> str:
    return _LABEL_KO.get(label.lower(), label)


def _fetch_from_cnn() -> Optional[dict]:
    try:
        req = urllib.request.Request(
            FEAR_GREED_URL,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://edition.cnn.com/",
                "Origin": "https://edition.cnn.com",
                "sec-fetch-site": "same-site",
                "sec-fetch-mode": "cors",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        score = data["fear_and_greed"]["score"]
        rating = data["fear_and_greed"]["rating"]
        return {"value": round(score), "label": _to_korean_label(rating), "source": "cnn"}
    except Exception:
        return None


def is_extreme_fear(value: int) -> bool:
    return value <= EXTREME_FEAR_MAX


def is_extreme_greed(value: int) -> bool:
    return value >= EXTREME_GREED_MIN
