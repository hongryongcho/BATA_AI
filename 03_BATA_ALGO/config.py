"""
BATA 알고리즘 설정 상수
"""

# 3배수 레버리지 ETF 목록
ETF_3X_CODES = {
    "SPXL", "UPRO",   # S&P 500 3x
    "TQQQ",           # Nasdaq 3x
    "SOXL",           # Semiconductor 3x
    "TECL",           # Technology 3x
    "FNGU",           # FANG+ 3x
    "LABU",           # Biotech 3x
    "CURE",           # Healthcare 3x
    "DFEN",           # Aerospace & Defense 3x
    "NAIL",           # Homebuilders 3x
    "WANT",           # Consumer Discretionary 3x
    "WEBL",           # Internet 3x
    "HIBL",           # S&P 500 High Beta 3x
}

# Fear & Greed 구간 경계
EXTREME_FEAR_MAX = 24   # 0~24: Extreme Fear
EXTREME_GREED_MIN = 75  # 75~100: Extreme Greed

# 기본 파라미터 (Google Sheets에서 오버라이드 가능)
DEFAULT_PARAMS = {
    "ticker": "SPY",
    "initial_capital": 100_000.0,
    "n_splits": 40,
    "start_date": "2022-01-01",
    "end_date": None,           # None = 오늘
    "base_profit_pct": 3.0,     # 기본 매도 수익 기준 (%)
    "buy_threshold_1": 10.0,    # 2배수 매수 낙폭 기준 (%)
    "buy_threshold_2": 15.0,    # 3배수 매수 낙폭 기준 (%)
    "buy_threshold_3": 20.0,    # 4배수 매수 낙폭 기준 (%)
    "sell_threshold_1": 10.0,   # 2배수 매도 수익 기준 (%)
    "sell_threshold_2": 20.0,   # 3배수 매도 수익 기준 (%)
    "sell_threshold_3": 30.0,   # 4배수 매도 수익 기준 (%)
    "gap_up_pct": 2.0,          # 갭업 강제 매도 기준 (%)
    "is_3x": False,             # 3배수 ETF 여부 (자동 감지 가능)
}

# Google Sheets 시트 이름
SHEET_SUMMARY = "Summary"
SHEET_BACKTEST = "Backtest"
SHEET_PERFORMANCE = "Performance"

# Google credentials 경로 (상대 경로)
# .env 파일에서 오버라이드 가능 (setup_auth.py 실행 시 자동 생성)
GOOGLE_CREDENTIALS_PATH = "../02_BATA_MQTT/config/google_credentials.json"
GOOGLE_TOKEN_PATH = "../02_BATA_MQTT/config/algo_token.json"  # Drive 토큰과 분리

# Fear & Greed API
FEAR_GREED_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
FEAR_GREED_ALT_URL = "https://api.alternative.me/fng/"
