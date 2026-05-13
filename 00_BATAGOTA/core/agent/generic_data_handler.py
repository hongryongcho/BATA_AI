"""
범용 데이터 리포트 핸들러
모든 데이터 타입의 리포트를 동일한 인터페이스로 처리
"""
import sys
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "02_BATA_MQTT"))


class GenericDataHandler:
    """범용 데이터 핸들러"""
    
    def __init__(self):
        self.output_dir = Path(__file__).parent.parent.parent / "outputs"
        self.output_dir.mkdir(exist_ok=True)
    
    def handle_data_report(self, params: dict) -> dict:
        """
        범용 데이터 리포트 생성
        
        Args:
            params: {
                data_type: "stock" | "crypto" | "weather" | ...
                time_range: "daily" | "weekly" | "monthly" | "yearly"
                format: "graph" | "table" | "csv"
                custom_params: {...}
            }
        
        Returns:
            {
                status: "success" | "error",
                data_type: str,
                output_file: str,
                output_type: str,
                summary: dict,
                error: str (실패 시)
            }
        """
        try:
            data_type = params.get("data_type", "").lower()
            time_range = params.get("time_range", "monthly")
            format_type = params.get("format", "graph")
            custom_params = params.get("custom_params", {})
            
            if not data_type:
                return {"status": "error", "error": "data_type is required"}
            
            # 데이터 타입별 처리 라우팅
            if data_type == "stock":
                return self._handle_stock(time_range, format_type, custom_params)
            elif data_type == "crypto":
                return self._handle_crypto(time_range, format_type, custom_params)
            elif data_type == "weather":
                return self._handle_weather(time_range, format_type, custom_params)
            else:
                return {
                    "status": "not_implemented",
                    "error": f"Data type '{data_type}' is not yet implemented",
                    "data_type": data_type,
                    "supported_types": ["stock", "crypto", "weather"]
                }
        
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "data_type": params.get("data_type", "unknown")
            }
    
    def _handle_stock(self, time_range: str, format_type: str, custom_params: dict) -> dict:
        """
        주식 데이터 처리 (실구현)
        
        Args:
            time_range: 시간 범위
            format_type: 출력 형식
            custom_params: {symbols: ["AAPL", "MSFT"], ...}
        
        Returns:
            {status, data_type, output_file, output_type, summary}
        """
        try:
            import yfinance as yf
            import pandas as pd

            symbols = custom_params.get("symbols", ["AAPL", "MSFT", "GOOGL"])
            if isinstance(symbols, str):
                symbols = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            symbols = [str(s).upper() for s in symbols]

            period_map = {
                "daily": "5d",
                "weekly": "1mo",
                "monthly": "6mo",
                "yearly": "1y",
            }
            interval_map = {
                "daily": "1h",
                "weekly": "1d",
                "monthly": "1d",
                "yearly": "1d",
            }
            period = period_map.get(time_range, "6mo")
            interval = interval_map.get(time_range, "1d")

            stock_df = self._fetch_stock_data(symbols, period=period, interval=interval)
            if stock_df.empty:
                return {
                    "status": "error",
                    "data_type": "stock",
                    "error": "No stock data fetched. Check symbols or network connectivity.",
                }

            summary = self._build_stock_summary(stock_df)
            output_file, output_type = self._write_stock_output(
                stock_df, summary, format_type=format_type, time_range=time_range
            )

            return {
                "status": "success",
                "data_type": "stock",
                "output_file": output_file,
                "output_type": output_type,
                "summary": summary,
                "rows": int(len(stock_df)),
            }
        except Exception as e:
            return {
                "status": "error",
                "data_type": "stock",
                "error": str(e),
            }

    def _fetch_stock_data(self, symbols: List[str], period: str, interval: str):
        import pandas as pd
        import yfinance as yf

        frames = []
        for symbol in symbols:
            df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
            if df is None or df.empty:
                continue

            if isinstance(df.columns, pd.MultiIndex):
                # ('Close', 'AAPL') -> 'Close' 형태로 단순화
                df.columns = [str(col[0]) for col in df.columns]

            df = df.reset_index()
            # yfinance 버전에 따라 datetime 컬럼명이 다를 수 있어 보정
            if "Datetime" in df.columns:
                df = df.rename(columns={"Datetime": "Date"})
            if "Date" not in df.columns and len(df.columns) > 0:
                first_col = df.columns[0]
                df = df.rename(columns={first_col: "Date"})

            keep_cols = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
            df = df[keep_cols]
            df["Symbol"] = symbol
            frames.append(df)

        if not frames:
            return pd.DataFrame()

        return pd.concat(frames, ignore_index=True)

    def _build_stock_summary(self, stock_df) -> Dict:
        summary = {}
        for symbol in sorted(stock_df["Symbol"].unique()):
            sdf = stock_df[stock_df["Symbol"] == symbol].sort_values("Date")
            if sdf.empty:
                continue

            first_close = float(sdf.iloc[0]["Close"]) if "Close" in sdf.columns else 0.0
            last_close = float(sdf.iloc[-1]["Close"]) if "Close" in sdf.columns else 0.0
            change_pct = ((last_close - first_close) / first_close * 100.0) if first_close else 0.0
            volume_sum = int(sdf["Volume"].fillna(0).sum()) if "Volume" in sdf.columns else 0

            summary[symbol] = {
                "first_close": round(first_close, 4),
                "last_close": round(last_close, 4),
                "change_pct": round(change_pct, 2),
                "rows": int(len(sdf)),
                "volume_sum": volume_sum,
            }
        return summary

    def _write_stock_output(self, stock_df, summary: Dict, format_type: str, time_range: str):
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if format_type == "csv":
            file_path = self.output_dir / f"stock_data_{time_range}_{timestamp}.csv"
            stock_df.sort_values(["Symbol", "Date"]).to_csv(file_path, index=False, encoding="utf-8")
            return str(file_path), "csv"

        if format_type == "table":
            file_path = self.output_dir / f"stock_table_{time_range}_{timestamp}.json"
            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "time_range": time_range,
                "summary": summary,
                "records": stock_df.sort_values(["Symbol", "Date"]).tail(200).to_dict(orient="records"),
            }
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return str(file_path), "json"

        # 기본값: graph
        import matplotlib.pyplot as plt

        file_path = self.output_dir / f"stock_graph_{time_range}_{timestamp}.png"
        fig, ax = plt.subplots(figsize=(10, 6))
        for symbol in sorted(stock_df["Symbol"].unique()):
            sdf = stock_df[stock_df["Symbol"] == symbol].sort_values("Date")
            if "Close" not in sdf.columns or sdf.empty:
                continue
            ax.plot(sdf["Date"], sdf["Close"], label=symbol)

        ax.set_title(f"Stock Close Price ({time_range})")
        ax.set_xlabel("Date")
        ax.set_ylabel("Close")
        ax.legend(loc="best")
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        plt.tight_layout()
        plt.savefig(file_path, dpi=140)
        plt.close(fig)

        return str(file_path), "png"
    
    def _handle_crypto(self, time_range: str, format_type: str, custom_params: dict) -> dict:
        """
        암호화폐 데이터 처리 (스켈레톤)
        
        Args:
            time_range: 시간 범위
            format_type: 출력 형식
            custom_params: {coins: ["bitcoin", "ethereum"], ...}
        
        Returns:
            {status: "not_implemented", ...}
        """
        return {
            "status": "not_implemented",
            "data_type": "crypto",
            "error": "Crypto handler will be implemented based on request",
            "expected_output": {
                "format": format_type,
                "time_range": time_range,
                "parameters": custom_params
            }
        }
    
    def _handle_weather(self, time_range: str, format_type: str, custom_params: dict) -> dict:
        """
        날씨 데이터 처리 (스켈레톤)
        
        Args:
            time_range: 시간 범위
            format_type: 출력 형식
            custom_params: {location: "Seoul", ...}
        
        Returns:
            {status: "not_implemented", ...}
        """
        return {
            "status": "not_implemented",
            "data_type": "weather",
            "error": "Weather handler will be implemented based on request",
            "expected_output": {
                "format": format_type,
                "time_range": time_range,
                "parameters": custom_params
            }
        }
    
    def _generate_file(self, data: dict, format_type: str, agent_name: str) -> tuple:
        """
        데이터를 파일로 생성
        
        Args:
            data: 생성할 데이터
            format_type: 파일 형식 (graph, table, csv)
            agent_name: 에이전트 이름
        
        Returns:
            (file_path, file_type)
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        
        if format_type == "graph":
            # PNG 그래프 생성
            file_path = self.output_dir / f"{agent_name}_graph_{timestamp}.png"
            return str(file_path), "png"
        elif format_type == "table":
            # HTML 테이블 생성
            file_path = self.output_dir / f"{agent_name}_table_{timestamp}.html"
            return str(file_path), "html"
        elif format_type == "csv":
            # CSV 파일 생성
            file_path = self.output_dir / f"{agent_name}_data_{timestamp}.csv"
            return str(file_path), "csv"
        else:
            # 기본값: JSON
            file_path = self.output_dir / f"{agent_name}_data_{timestamp}.json"
            return str(file_path), "json"


def generic_router(intent: str, params: dict = None) -> dict:
    """범용 데이터 핸들러 라우터"""
    if params is None:
        params = {}
    
    handler = GenericDataHandler()
    
    if intent == "data_report":
        return handler.handle_data_report(params)
    else:
        return {
            "status": "error",
            "error": f"Unknown intent: {intent}",
            "intent": intent
        }


if __name__ == "__main__":
    # 테스트
    import json
    
    handler = GenericDataHandler()
    
    # 테스트 1: Stock 요청
    result = handler.handle_data_report({
        "data_type": "stock",
        "time_range": "monthly",
        "format": "graph",
        "custom_params": {
            "symbols": ["AAPL", "MSFT", "GOOGL"],
            "start_date": "2025-01-01",
            "end_date": "2025-12-31"
        }
    })
    print("Stock Report:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    
    # 테스트 2: Crypto 요청
    result = handler.handle_data_report({
        "data_type": "crypto",
        "time_range": "yearly",
        "format": "csv"
    })
    print("Crypto Report:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
