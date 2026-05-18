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
        {"value": int, "label": str, "source": str}
        value: 0~100, label: 예) "Extreme Fear", source: "cnn" or "alternative"
    """
    result = _fetch_from_cnn()
    if result is None:
        result = _fetch_from_alternative()
    if result is None:
        # 데이터 없을 경우 중립값 반환
        return {"value": 50, "label": "Neutral", "source": "fallback"}
    return result


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
        return {"value": round(score), "label": rating, "source": "cnn"}
    except Exception:
        return None


def _fetch_from_alternative() -> Optional[dict]:
    try:
        req = urllib.request.Request(
            FEAR_GREED_ALT_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        item = data["data"][0]
        return {
            "value": int(item["value"]),
            "label": item["value_classification"],
            "source": "alternative",
        }
    except Exception:
        return None


def is_extreme_fear(value: int) -> bool:
    return value <= EXTREME_FEAR_MAX


def is_extreme_greed(value: int) -> bool:
    return value >= EXTREME_GREED_MIN
