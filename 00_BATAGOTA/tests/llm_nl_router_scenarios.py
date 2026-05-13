"""
자연어 -> LLM intent 라우터 -> route_intent 통합 시나리오 테스트
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent.llm_intent_router import route_natural_language
from core.agent.main import route_intent


def run_case(name: str, text: str):
    parsed = route_natural_language(text)
    print("=" * 80)
    print(f"SCENARIO: {name}")
    print(f"INPUT: {text}")
    print(f"PARSED: {json.dumps(parsed, ensure_ascii=False)}")

    if parsed.get("status") != "ready":
        print(f"RESULT: FAIL (router status={parsed.get('status')})")
        return False

    result = route_intent(parsed["intent"], parsed.get("params", {}), auto_upload=False)
    print(f"EXECUTE: status={result.get('status')} intent={result.get('intent')}")

    if result.get("status") == "error":
        print(f"ERROR: {result.get('error')}")
        return False

    if result.get("output_file"):
        print(f"OUTPUT_FILE: {result.get('output_file')}")

    print("RESULT: PASS")
    return True


def run_clarify_case(name: str, text: str):
    parsed = route_natural_language(text)
    print("=" * 80)
    print(f"SCENARIO: {name}")
    print(f"INPUT: {text}")
    print(f"PARSED: {json.dumps(parsed, ensure_ascii=False)}")

    if parsed.get("status") != "clarify":
        print(f"RESULT: FAIL (expected clarify, got {parsed.get('status')})")
        return False

    if not parsed.get("suggested_payload"):
        print("RESULT: FAIL (missing suggested_payload)")
        return False

    print("RESULT: PASS")
    return True


def main():
    scenarios = [
        ("mqtt connection info", "MQTT 브로커 주소와 포트번호 알려줘"),
        ("mqtt clients", "현재 접속자 수 보여줘"),
        ("topic list", "수신중인 토픽 목록 보여줘"),
        ("topic add", "M2 토픽 추가해줘"),
        ("topic remove", "M2 토픽 제거해줘"),
        ("db recent 20", "DB 최근 20건 보여줘"),
        ("backup status", "최근 백업 상태 보여줘"),
        ("stock graph", "지난달 애플이랑 엔비디아 그래프 보내줘"),
    ]

    passed = 0
    for name, text in scenarios:
        ok = run_case(name, text)
        passed += 1 if ok else 0

    # 명확한 의도가 없는 요청은 분석 후 실행 제안 payload를 제공해야 한다.
    passed += 1 if run_clarify_case("ambiguous request", "그거 알려줘") else 0

    print("=" * 80)
    total = len(scenarios) + 1
    print(f"SUMMARY: {passed}/{total} passed")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
