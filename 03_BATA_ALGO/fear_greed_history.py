"""
Fear & Greed 역사 데이터 페처
──────────────────────────────
CNN 공개 API 에서 ~3년치 일별 F&G 지수 다운로드 + 로컬 CSV 캐시.

사용:
    from fear_greed_history import load_fng_history
    fng = load_fng_history()   # pd.Series, index=날짜, value=0~100 int
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

CACHE_DIR  = Path(__file__).parent / "cache" / "fng"
CACHE_FILE = CACHE_DIR / "fng_history.csv"

# CNN graphdata 엔드포인트 (start_date 포함 최대 ~3년 반환)
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}"

# Alternative.me 일별 히스토리 (최대 limit 건)
ALT_URL = "https://api.alternative.me/fng/?limit=2000&format=json&date_format=us"


# ──────────────────────────────────────────────────────────
# 공개 API 페처
# ──────────────────────────────────────────────────────────

def _fetch_cnn(start: str = "2021-01-01") -> pd.Series | None:
    """CNN 주식시장 F&G 역사 데이터. subprocess+curl로 봇 차단 우회.
    ※ Alternative.me(암호화폐 기반)와 혼용 금지."""
    url = CNN_URL.format(start=start)
    try:
        result = subprocess.run(
            [
                "curl", "-s",
                "-A", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "-H", "Accept: application/json, text/plain, */*",
                "-H", "Accept-Language: en-US,en;q=0.9",
                "-H", "Referer: https://www.cnn.com/",
                "-H", "Origin: https://www.cnn.com",
                "--compressed",
                url,
            ],
            capture_output=True, text=True, timeout=25,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"[FnG] CNN curl 실패 (returncode={result.returncode})")
            return None
        data = json.loads(result.stdout)
        records = data.get("fear_and_greed_historical", {}).get("data", [])
        if not records:
            return None
        rows = []
        for rec in records:
            ts = rec.get("x") or rec.get("timestamp")
            val = rec.get("y") or rec.get("score")
            if ts and val is not None:
                dt = datetime.utcfromtimestamp(float(ts) / 1000).strftime("%Y-%m-%d")
                rows.append({"date": dt, "fng": int(round(float(val)))})
        if not rows:
            return None
        df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
        s = pd.Series(df["fng"].values, index=pd.to_datetime(df["date"]), name="fng")
        return s
    except Exception as e:
        print(f"[FnG] CNN fetch 실패: {e}")
        return None


def _fetch_alternative() -> pd.Series | None:
    """Alternative.me 최대 2000일치"""
    try:
        req = urllib.request.Request(
            ALT_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        rows = []
        for item in data.get("data", []):
            # date_format=us → "MM/DD/YYYY"
            raw_date = item.get("timestamp") or item.get("date") or ""
            val = item.get("value")
            if raw_date and val is not None:
                try:
                    dt = pd.to_datetime(raw_date)
                    rows.append({"date": dt.strftime("%Y-%m-%d"), "fng": int(val)})
                except Exception:
                    pass
        if not rows:
            return None
        df = pd.DataFrame(rows).drop_duplicates("date").sort_values("date")
        s = pd.Series(df["fng"].values, index=pd.to_datetime(df["date"]), name="fng")
        return s
    except Exception as e:
        print(f"[FnG] Alternative fetch 실패: {e}")
        return None


# ──────────────────────────────────────────────────────────
# 캐시 관리
# ──────────────────────────────────────────────────────────

def _load_cache() -> pd.Series | None:
    if not CACHE_FILE.exists():
        return None
    try:
        df = pd.read_csv(CACHE_FILE, parse_dates=["date"], index_col="date")
        return df["fng"].rename("fng")
    except Exception:
        return None


def _save_cache(s: pd.Series):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    s.rename_axis("date").reset_index().to_csv(CACHE_FILE, index=False)


def _is_fresh(s: pd.Series) -> bool:
    """오늘(또는 직전 영업일)까지 데이터가 있으면 fresh"""
    if s is None or s.empty:
        return False
    latest = s.index.max().date()
    today  = datetime.now().date()
    # 오늘이 주말이면 금요일까지면 OK
    threshold = today - timedelta(days=3)
    return latest >= threshold


# ──────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────

def load_fng_history(force_refresh: bool = False) -> pd.Series:
    """
    Returns
    -------
    pd.Series
        index : DatetimeIndex (일별)
        values: int 0~100 (Fear & Greed score)
        name  : "fng"
    """
    cached = _load_cache()

    if not force_refresh and _is_fresh(cached):
        print(f"[FnG] 캐시 사용 ({cached.index.min().date()} ~ {cached.index.max().date()}, {len(cached)}일)")
        return cached

    print("[FnG] 최신 데이터 다운로드 중...")

    # CNN 주식시장 F&G 수집 (curl 기반)
    fresh = _fetch_cnn(start="2021-01-01")

    # ※ Alternative.me는 암호화폐(비트코인) 기반 지수 → 주식 백테스트에 사용 불가, 폴백 제거
    if fresh is None or len(fresh) < 100:
        print("[FnG] CNN 수집 실패 → 기존 캐시 유지 (Alternative.me 폴백 사용 안 함)")

    # 캐시 병합 (과거 데이터 보존)
    if fresh is not None and len(fresh) > 0:
        if cached is not None and len(cached) > 0:
            combined = pd.concat([cached, fresh])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        else:
            combined = fresh.sort_index()
        _save_cache(combined)
        print(f"[FnG] 저장 완료 ({combined.index.min().date()} ~ {combined.index.max().date()}, {len(combined)}일)")
        return combined

    # 모두 실패 → 캐시 반환
    if cached is not None:
        print("[FnG] ⚠️ 네트워크 실패, 캐시 반환")
        return cached

    raise RuntimeError("[FnG] Fear & Greed 데이터를 가져올 수 없습니다.")


def get_fng_for_dates(dates: pd.DatetimeIndex, fill_method: str = "ffill") -> pd.Series:
    """
    주어진 날짜 배열에 맞게 F&G 값을 맞춤 정렬 (ffill 기본).
    주말/공휴일은 직전 값으로 채움.
    """
    fng = load_fng_history()
    aligned = fng.reindex(dates, method=fill_method)
    # 앞부분 NaN → 중립값 50
    aligned = aligned.fillna(50).astype(int)
    return aligned


if __name__ == "__main__":
    s = load_fng_history(force_refresh=True)
    print(s.tail(10))
