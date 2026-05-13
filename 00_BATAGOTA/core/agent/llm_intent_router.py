"""
LLM 기반 자연어 Intent 라우터
- 사용자 자연어를 intent + params 구조로 변환
- JSON 스키마 수준 검증
- LLM 실패 시 규칙 기반 폴백
"""
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MQTT_ROOT = PROJECT_ROOT.parent / "02_BATA_MQTT"

load_dotenv(PROJECT_ROOT / "config" / ".env")
load_dotenv(MQTT_ROOT / ".env")

ALLOWED_INTENTS = {
    "mqtt_report",
    "mqtt_clients",
    "backup_status",
    "retention_status",
    "mqtt_connection_info",
    "mqtt_topic_list",
    "mqtt_topic_add",
    "mqtt_topic_remove",
    "db_recent",
    "data_report",
}

ALLOWED_DATA_TYPES = {"stock", "crypto", "weather"}
ALLOWED_TIME_RANGE = {"daily", "weekly", "monthly", "yearly"}
ALLOWED_FORMAT = {"graph", "table", "csv"}

ROUTER_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["intent", "params", "confidence"],
    "properties": {
        "intent": {
            "type": "string",
            "enum": sorted(list(ALLOWED_INTENTS)),
        },
        "params": {
            "type": "object",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },
}


def route_natural_language(text: str) -> Dict[str, Any]:
    """
    자연어 텍스트를 intent 라우팅 정보로 변환한다.

    Returns:
        {
          status: ready|clarify|error,
          intent: str,
          params: dict,
          confidence: float,
          source: llm|fallback,
          message: str,
        }
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return {
            "status": "clarify",
            "message": "요청이 비어 있습니다. 예: 지난달 AAPL 그래프 보여줘",
        }

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        llm_result = _parse_with_anthropic(cleaned, api_key)
        if llm_result.get("ok"):
            candidate = llm_result["data"]
            valid, reason = validate_router_payload(candidate)
            if valid:
                normalized = normalize_router_payload(candidate)
                return {
                    "status": "ready",
                    "intent": normalized["intent"],
                    "params": normalized["params"],
                    "confidence": float(normalized.get("confidence", 0.8)),
                    "source": "llm",
                }

    fallback = _fallback_parse(cleaned)
    valid, reason = validate_router_payload(fallback)
    if not valid:
        suggested = _build_suggested_payload(cleaned)
        return {
            "status": "clarify",
            "message": f"요청 해석이 불명확합니다: {reason}",
            "source": "fallback",
            "suggested_payload": suggested,
        }

    normalized = normalize_router_payload(fallback)
    return {
        "status": "ready",
        "intent": normalized["intent"],
        "params": normalized["params"],
        "confidence": float(normalized.get("confidence", 0.6)),
        "source": "fallback",
    }


def validate_router_payload(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """라우터 결과를 JSON 스키마 규칙으로 검증한다."""
    if not isinstance(payload, dict):
        return False, "payload must be object"

    for req in ROUTER_OUTPUT_SCHEMA["required"]:
        if req not in payload:
            return False, f"missing required field: {req}"

    intent = payload.get("intent")
    if not isinstance(intent, str) or intent not in ALLOWED_INTENTS:
        return False, f"invalid intent: {intent}"

    params = payload.get("params")
    if not isinstance(params, dict):
        return False, "params must be object"

    confidence = payload.get("confidence")
    try:
        confidence = float(confidence)
    except Exception:
        return False, "confidence must be number"
    if confidence < 0 or confidence > 1:
        return False, "confidence must be 0..1"

    if intent == "data_report":
        dt = params.get("data_type")
        if dt not in ALLOWED_DATA_TYPES:
            return False, f"data_type must be one of {sorted(ALLOWED_DATA_TYPES)}"

        tr = params.get("time_range", "monthly")
        if tr not in ALLOWED_TIME_RANGE:
            return False, f"time_range must be one of {sorted(ALLOWED_TIME_RANGE)}"

        fmt = params.get("format", "graph")
        if fmt not in ALLOWED_FORMAT:
            return False, f"format must be one of {sorted(ALLOWED_FORMAT)}"

        cp = params.get("custom_params", {})
        if not isinstance(cp, dict):
            return False, "custom_params must be object"

    if intent == "mqtt_connection_info":
        # 현재는 params 없이도 충분하다.
        if params and not isinstance(params, dict):
            return False, "params must be object"

    if intent in {"mqtt_topic_add", "mqtt_topic_remove"}:
        machine_no = params.get("machine_no")
        if machine_no is None:
            return False, "machine_no is required for mqtt_topic_add/mqtt_topic_remove"
        try:
            machine_no = int(machine_no)
        except Exception:
            return False, "machine_no must be integer"
        if machine_no < 1 or machine_no > 999:
            return False, "machine_no must be in range 1..999"

    if intent == "db_recent":
        limit = params.get("limit", 20)
        try:
            limit = int(limit)
        except Exception:
            return False, "limit must be integer"
        if limit < 1 or limit > 100:
            return False, "limit must be in range 1..100"

    return True, "ok"


def normalize_router_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """검증 가능한 최소 정규화."""
    intent = payload["intent"]
    params = dict(payload.get("params", {}))

    if intent == "data_report":
        params.setdefault("data_type", "stock")
        params.setdefault("time_range", "monthly")
        params.setdefault("format", "graph")
        params.setdefault("custom_params", {})

        symbols = params["custom_params"].get("symbols")
        if isinstance(symbols, str):
            params["custom_params"]["symbols"] = [s.strip().upper() for s in symbols.split(",") if s.strip()]

    return {
        "intent": intent,
        "params": params,
        "confidence": float(payload.get("confidence", 0.7)),
    }


def _parse_with_anthropic(text: str, api_key: str) -> Dict[str, Any]:
    """Anthropic 모델로 JSON intent 추론."""
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "너는 Telegram 자연어 요청을 intent JSON으로 변환하는 라우터다. "
            "반드시 JSON만 출력한다. 설명 문장 금지.\n"
            "허용 intent: mqtt_report, mqtt_clients, backup_status, retention_status, mqtt_connection_info, data_report\n"
            "추가 intent: mqtt_topic_list, mqtt_topic_add, mqtt_topic_remove, db_recent\n"
            "mqtt_topic_add/remove params: machine_no(1..999 정수)\n"
            "db_recent params: limit(1..100 정수, 기본 20)\n"
            "data_report params: data_type(stock|crypto|weather), time_range(daily|weekly|monthly|yearly), format(graph|table|csv), custom_params(object)\n"
            "mqtt_connection_info는 MQTT 브로커 주소, 포트, 토픽을 묻는 요청에 사용한다.\n"
            "mqtt_clients는 MQTT 동시 접속자 수를 묻는 요청에 사용한다.\n"
            "mqtt_topic_list는 현재 수신(관리) 중인 Topic 목록 요청에 사용한다.\n"
            "db_recent는 DB 최근 로그 N건 조회 요청에 사용한다.\n"
            "출력 스키마: {\"intent\": string, \"params\": object, \"confidence\": number}\n"
            f"사용자 입력: {text}"
        )

        resp = client.messages.create(
            model="claude-3-5-sonnet-latest",
            max_tokens=300,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )

        content = ""
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                content += block.text

        data = _extract_json_object(content)
        if data is None:
            return {"ok": False, "error": "llm json parse failed"}
        return {"ok": True, "data": data}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _extract_json_object(text: str):
    if not text:
        return None

    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None

    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _fallback_parse(text: str) -> Dict[str, Any]:
    lower = text.lower()

    count_match = re.search(r"(\d{1,3})\s*건", lower)
    if any(k in lower for k in ["최근", "recent", "db", "로그", "행", "레코드"]):
        if any(k in lower for k in ["보여", "조회", "확인", "뽑", "캡처", "list"]):
            limit = int(count_match.group(1)) if count_match else 20
            if limit < 1:
                limit = 1
            if limit > 100:
                limit = 100
            return {"intent": "db_recent", "params": {"limit": limit}, "confidence": 0.9}

    if any(k in lower for k in ["수신중", "수신 중", "topic list", "토픽 목록", "구독 목록", "현재 topic", "현재 토픽"]):
        return {"intent": "mqtt_topic_list", "params": {}, "confidence": 0.9}

    if any(k in lower for k in ["동시 접속", "접속자 수", "clients", "current clients", "현재 접속자"]):
        return {"intent": "mqtt_clients", "params": {}, "confidence": 0.9}

    add_match = re.search(r"m\s*(\d{1,3})", lower)
    if add_match and any(k in lower for k in ["topic add", "토픽 추가", "구독 추가", "추가해줘"]):
        return {
            "intent": "mqtt_topic_add",
            "params": {"machine_no": int(add_match.group(1))},
            "confidence": 0.9,
        }

    if add_match and any(k in lower for k in ["topic remove", "토픽 제거", "구독 제거", "삭제해줘"]):
        return {
            "intent": "mqtt_topic_remove",
            "params": {"machine_no": int(add_match.group(1))},
            "confidence": 0.9,
        }

    if any(k in lower for k in ["브로커", "broker", "host", "주소", "포트", "port", "mqtt 주소"]):
        return {"intent": "mqtt_connection_info", "params": {}, "confidence": 0.9}

    if any(k in lower for k in ["mqtt", "상태", "로그 현황"]) and "백업" not in lower and "정리" not in lower:
        return {"intent": "mqtt_report", "params": {}, "confidence": 0.7}

    if any(k in lower for k in ["backup", "백업"]):
        return {"intent": "backup_status", "params": {}, "confidence": 0.8}

    if any(k in lower for k in ["retention", "정리", "삭제"]):
        return {"intent": "retention_status", "params": {}, "confidence": 0.8}

    data_related = any(
        k in lower for k in [
            "stock", "주식", "crypto", "코인", "암호화폐", "weather", "날씨",
            "그래프", "graph", "csv", "table", "리포트", "report"
        ]
    )

    if not data_related:
        return {"intent": "", "params": {}, "confidence": 0.0}

    data_type = "stock"
    if any(k in lower for k in ["crypto", "코인", "암호화폐", "bitcoin", "ethereum"]):
        data_type = "crypto"
    elif any(k in lower for k in ["weather", "날씨"]):
        data_type = "weather"

    time_range = "monthly"
    if any(k in lower for k in ["daily", "일간", "오늘"]):
        time_range = "daily"
    elif any(k in lower for k in ["weekly", "주간", "이번주"]):
        time_range = "weekly"
    elif any(k in lower for k in ["yearly", "연간", "1년", "작년"]):
        time_range = "yearly"

    fmt = "graph"
    if "csv" in lower:
        fmt = "csv"
    elif any(k in lower for k in ["table", "표", "json"]):
        fmt = "table"

    symbol_map = {
        "애플": "AAPL",
        "apple": "AAPL",
        "마소": "MSFT",
        "microsoft": "MSFT",
        "엔비디아": "NVDA",
        "nvidia": "NVDA",
        "구글": "GOOGL",
        "google": "GOOGL",
        "아마존": "AMZN",
        "amazon": "AMZN",
        "메타": "META",
        "tesla": "TSLA",
    }

    symbols: List[str] = []
    for key, sym in symbol_map.items():
        if key in lower and sym not in symbols:
            symbols.append(sym)

    for token in re.findall(r"\b[A-Z]{1,5}\b", text):
        if token not in symbols and token not in {"CSV", "JSON"}:
            symbols.append(token)

    if not symbols and data_type == "stock":
        symbols = ["AAPL", "MSFT", "NVDA"]

    params = {
        "data_type": data_type,
        "time_range": time_range,
        "format": fmt,
        "custom_params": {"symbols": symbols} if data_type == "stock" else {},
    }

    return {"intent": "data_report", "params": params, "confidence": 0.65}


def _build_suggested_payload(text: str) -> Dict[str, Any]:
    """모호한 요청일 때 사용자가 바로 실행 가능한 요청 형태를 제안한다."""
    lower = (text or "").lower()
    if any(k in lower for k in ["최근", "recent", "db", "로그", "행", "레코드"]):
        return {"intent": "db_recent", "params": {"limit": 20}}

    if any(k in lower for k in ["mqtt", "브로커", "host", "port", "포트"]):
        return {"intent": "mqtt_connection_info", "params": {}}

    if any(k in lower for k in ["topic", "토픽", "구독"]):
        return {"intent": "mqtt_topic_list", "params": {}}

    return {
        "intent": "data_report",
        "params": {
            "data_type": "stock",
            "time_range": "monthly",
            "format": "graph",
            "custom_params": {"symbols": ["AAPL", "NVDA"]},
        },
    }
