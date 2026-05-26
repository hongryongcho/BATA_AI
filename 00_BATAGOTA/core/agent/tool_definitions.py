import json
import sys
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALGO_ROOT = PROJECT_ROOT.parent / "03_BATA_ALGO"

TOOL_DEFINITIONS: List[dict] = [
    {
        "name": "get_mqtt_status",
        "description": "MQTT 브로커 및 DB 전체 상태 리포트를 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_mqtt_clients",
        "description": "현재 MQTT 브로커에 동시 접속 중인 클라이언트 수를 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_mqtt_connection_info",
        "description": "MQTT 브로커 호스트, 포트, 토픽 설정 정보를 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_db_recent",
        "description": "SQLite DB에 최근 저장된 MQTT 로그를 조회한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "조회할 최대 건수 (1~100, 기본값 20)",
                    "minimum": 1,
                    "maximum": 100,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_topic_list",
        "description": "현재 관리 중인 MQTT 토픽 목록을 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_topic",
        "description": "지정한 Machine number에 대한 MQTT 토픽을 구독 목록에 추가한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_no": {
                    "type": "integer",
                    "description": "추가할 Machine 번호 (1~999)",
                    "minimum": 1,
                    "maximum": 999,
                }
            },
            "required": ["machine_no"],
        },
    },
    {
        "name": "remove_topic",
        "description": "지정한 Machine number에 대한 MQTT 토픽을 구독 목록에서 제거한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "machine_no": {
                    "type": "integer",
                    "description": "제거할 Machine 번호 (1~999)",
                    "minimum": 1,
                    "maximum": 999,
                }
            },
            "required": ["machine_no"],
        },
    },
    {
        "name": "get_backup_status",
        "description": "DB 백업 실행 현황을 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_retention_status",
        "description": "DB 로그 정리(보존 기간 초과 삭제) 현황을 반환한다.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_stock_data",
        "description": (
            "주식 데이터를 조회하고 그래프/테이블/CSV 파일로 생성한다. "
            "symbols를 지정하지 않으면 대형 기술주 7종목을 기본 사용한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "티커 심볼 목록 (예: ['AAPL', 'NVDA'])",
                },
                "time_range": {
                    "type": "string",
                    "enum": ["daily", "weekly", "monthly", "yearly"],
                    "description": "조회 기간 (기본값: monthly)",
                },
                "format": {
                    "type": "string",
                    "enum": ["graph", "table", "csv"],
                    "description": "출력 형식 (기본값: graph)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "get_fear_greed_index",
        "description": (
            "CNN Fear & Greed Index 현재 값을 조회한다. "
            "0~24: Extreme Fear, 25~49: Fear, 50: Neutral, "
            "51~74: Greed, 75~100: Extreme Greed."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """
    tool_name + tool_input을 받아 기존 핸들러로 디스패치한다.
    반환: {status, data, output_file, output_type}
    """
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from core.agent.main import route_intent

    try:
        if tool_name == "get_mqtt_status":
            r = route_intent("mqtt_report", {}, auto_upload=False)

        elif tool_name == "get_mqtt_clients":
            r = route_intent("mqtt_clients", {}, auto_upload=False)

        elif tool_name == "get_mqtt_connection_info":
            r = route_intent("mqtt_connection_info", {}, auto_upload=False)

        elif tool_name == "get_db_recent":
            limit = int(tool_input.get("limit", 20))
            r = route_intent("db_recent", {"limit": limit}, auto_upload=False)

        elif tool_name == "get_topic_list":
            r = route_intent("mqtt_topic_list", {}, auto_upload=False)

        elif tool_name == "add_topic":
            r = route_intent("mqtt_topic_add", {"machine_no": int(tool_input["machine_no"])}, auto_upload=False)

        elif tool_name == "remove_topic":
            r = route_intent("mqtt_topic_remove", {"machine_no": int(tool_input["machine_no"])}, auto_upload=False)

        elif tool_name == "get_backup_status":
            r = route_intent("backup_status", {}, auto_upload=False)

        elif tool_name == "get_retention_status":
            r = route_intent("retention_status", {}, auto_upload=False)

        elif tool_name == "get_stock_data":
            symbols = tool_input.get("symbols", ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"])
            r = route_intent("data_report", {
                "data_type": "stock",
                "time_range": tool_input.get("time_range", "monthly"),
                "format": tool_input.get("format", "graph"),
                "custom_params": {"symbols": symbols},
            }, auto_upload=False)

        elif tool_name == "get_fear_greed_index":
            return _exec_fear_greed()

        else:
            return {"status": "error", "data": {"error": f"Unknown tool: {tool_name}"}, "output_file": None, "output_type": None}

        return {
            "status": r.get("status", "error"),
            "data": r,
            "output_file": r.get("output_file"),
            "output_type": r.get("output_type"),
        }

    except Exception as e:
        return {"status": "error", "data": {"error": str(e)}, "output_file": None, "output_type": None}


def _exec_fear_greed() -> dict:
    if str(ALGO_ROOT) not in sys.path:
        sys.path.insert(0, str(ALGO_ROOT))
    try:
        from fear_greed import fetch_fear_greed, is_extreme_fear, is_extreme_greed
        fng = fetch_fear_greed()
        val = fng.get("value", 0)
        return {
            "status": "success",
            "data": {
                "value": val,
                "label": fng.get("label", ""),
                "source": fng.get("source", ""),
                "is_extreme_fear": is_extreme_fear(val),
                "is_extreme_greed": is_extreme_greed(val),
            },
            "output_file": None,
            "output_type": None,
        }
    except Exception as e:
        return {"status": "error", "data": {"error": str(e)}, "output_file": None, "output_type": None}
