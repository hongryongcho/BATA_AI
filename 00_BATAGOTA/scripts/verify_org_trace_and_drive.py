import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent.llm_intent_router import route_natural_language
from core.agent.main import route_intent


def main() -> int:
    text = "지난달 애플이랑 엔비디아 주식 그래프 만들어서 드라이브에 올려줘"

    parsed = route_natural_language(text)
    print("[STEP1] route_natural_language")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))

    if parsed.get("status") != "ready":
        print("[FAIL] 라우터가 ready 상태를 반환하지 않았습니다.")
        return 2

    intent = parsed["intent"]
    params = parsed.get("params", {})

    result = route_intent(intent, params, auto_upload=True)
    print("\n[STEP2] route_intent(auto_upload=True)")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    org_trace = result.get("org_trace")
    if org_trace:
        print("\n[CHECK] org_trace found")
    else:
        print("\n[CHECK] org_trace missing")

    output_file = result.get("output_file")
    if output_file and Path(output_file).exists():
        print(f"[CHECK] output_file exists: {output_file}")
    else:
        print(f"[CHECK] output_file missing or not found: {output_file}")

    drive_link = result.get("drive_link")
    if drive_link:
        print(f"[CHECK] drive_link: {drive_link}")
    else:
        print("[CHECK] drive_link missing")
        if result.get("drive_upload_error"):
            print(f"[CHECK] drive_upload_error: {result.get('drive_upload_error')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
