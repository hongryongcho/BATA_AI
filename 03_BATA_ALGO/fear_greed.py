"""
Fear & Greed 지수 조회
CNN 우선, 실패 시 Alternative.me 폴백
"""

import json
import urllib.request
from typing import Optional
from config import FEAR_GREED_URL, FEAR_GREED_ALT_URL, EXTREME_FEAR_MAX, EXTREME_GREED_MIN


def fetch_fear_greed() -> dict:
    """
    Returns:
        {"value": int, "label": str, "source": str, "error": bool}

    CNN만 사용. 실패 시 중앙값 50으로 대체하되 error=True 플래그를 함께 반환.
    대체 중임을 UI에서 반드시 표시해야 함.
    """
    result = _fetch_from_cnn()
    if result is None:
        return {"value": 50, "label": "중립", "source": "fallback", "error": True}
    return result


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
