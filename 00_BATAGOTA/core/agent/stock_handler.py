"""
주식 데이터 핸들러
generic_data_handler 위의 특화된 래퍼
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "02_BATA_MQTT"))

from generic_data_handler import GenericDataHandler


class StockHandler:
    """주식 데이터 전문 핸들러"""
    
    def __init__(self):
        self.generic_handler = GenericDataHandler()
    
    def handle_stock_report(self, params: dict) -> dict:
        """
        주식 리포트 생성
        
        Args:
            params: {
                symbols: ["AAPL", "MSFT", ...] (선택),
                time_range: "daily" | "monthly" | "yearly",
                format: "graph" | "table" | "csv",
                start_date: "YYYY-MM-DD" (선택),
                end_date: "YYYY-MM-DD" (선택)
            }
        
        Returns:
            {status, output_file, output_type, summary, ...}
        """
        # 기본값 설정
        symbols = params.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"])
        time_range = params.get("time_range", "monthly")
        format_type = params.get("format", "graph")
        
        # generic_data_handler로 라우팅
        return self.generic_handler.handle_data_report({
            "data_type": "stock",
            "time_range": time_range,
            "format": format_type,
            "custom_params": {
                "symbols": symbols,
                "start_date": params.get("start_date"),
                "end_date": params.get("end_date")
            }
        })
    
    def handle_stock_compare(self, params: dict) -> dict:
        """
        여러 주식 비교 리포트
        
        Args:
            params: {
                symbols: ["AAPL", "MSFT", ...],
                metric: "price" | "volume" | "volatility",
                time_range: "daily" | "monthly" | "yearly",
                format: "graph" | "table"
            }
        
        Returns:
            {status, output_file, ...}
        """
        symbols = params.get("symbols", [])
        metric = params.get("metric", "price")
        time_range = params.get("time_range", "monthly")
        format_type = params.get("format", "graph")
        
        if not symbols:
            return {
                "status": "error",
                "error": "symbols is required for comparison",
                "expected_format": ["AAPL", "MSFT", "GOOGL"]
            }
        
        return self.generic_handler.handle_data_report({
            "data_type": "stock",
            "time_range": time_range,
            "format": format_type,
            "custom_params": {
                "symbols": symbols,
                "comparison_mode": True,
                "metric": metric
            }
        })


def stock_router(intent: str, params: dict = None) -> dict:
    """주식 핸들러 라우터"""
    if params is None:
        params = {}
    
    handler = StockHandler()
    
    if intent == "stock_analyze":
        return handler.handle_stock_report(params)
    elif intent == "stock_compare":
        return handler.handle_stock_compare(params)
    else:
        return {
            "status": "error",
            "error": f"Unknown stock intent: {intent}",
            "intent": intent
        }


if __name__ == "__main__":
    import json
    
    handler = StockHandler()
    
    # 테스트 1: 기본 주식 리포트
    result = handler.handle_stock_report({
        "time_range": "monthly",
        "format": "graph"
    })
    print("Stock Report (7 Big Tech):")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    
    # 테스트 2: 커스텀 주식 리포트
    result = handler.handle_stock_report({
        "symbols": ["AAPL", "MSFT"],
        "time_range": "yearly",
        "format": "csv"
    })
    print("Custom Stock Report:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print()
    
    # 테스트 3: 주식 비교
    result = handler.handle_stock_compare({
        "symbols": ["AAPL", "MSFT", "GOOGL"],
        "metric": "volatility",
        "format": "table"
    })
    print("Stock Comparison:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
