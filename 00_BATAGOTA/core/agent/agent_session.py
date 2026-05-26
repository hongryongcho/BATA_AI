import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import anthropic
except ImportError:
    print("[agent_session] anthropic 패키지 미설치. pip install anthropic")
    raise

from core.memory.conversation_store import ConversationStore
from core.agent.tool_definitions import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """당신은 BATAGOTA 시스템의 AI 비서입니다.

역할:
- MQTT 브로커, 데이터베이스 상태, 주식 데이터, Fear & Greed 지수를 조회하고 분석합니다.
- 사용자의 자연어 요청을 이해하고, 필요한 도구를 호출하여 정확한 정보를 제공합니다.
- 항상 한국어로 응답합니다.
- 답변은 간결하고 명확하게 작성합니다.
- 도구 호출 결과를 바탕으로 자연스러운 문장으로 요약합니다.

운영 원칙:
- 사용자가 모호한 요청을 하면 적절한 도구를 선택하거나 확인 질문을 합니다.
- 도구 결과에 오류가 있으면 사용자에게 명확히 안내합니다.
- 주식 그래프나 파일이 생성된 경우 파일이 함께 전송됩니다.
- 개인 정보나 민감한 시스템 정보는 신중하게 다룹니다."""


def _serialize_content(content) -> str:
    if isinstance(content, str):
        return json.dumps(content, ensure_ascii=False)
    if isinstance(content, list):
        serializable = []
        for block in content:
            if hasattr(block, "model_dump"):
                serializable.append(block.model_dump())
            elif isinstance(block, dict):
                serializable.append(block)
            else:
                serializable.append(str(block))
        return json.dumps(serializable, ensure_ascii=False)
    return json.dumps(str(content), ensure_ascii=False)


def _to_api_content(content):
    """SQLite에서 로드한 content를 Anthropic API messages 형식으로 변환한다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        result = []
        for block in content:
            if isinstance(block, dict):
                result.append(block)
            else:
                result.append(str(block))
        return result
    return str(content)


class AgentSession:
    MODEL = "claude-sonnet-4-6"
    MAX_HISTORY = 20
    MAX_TOOL_ROUNDS = 10

    def __init__(self, api_key: Optional[str] = None, db_path: Optional[Path] = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self._store = ConversationStore(db_path)

    def chat(self, user_id: str, text: str) -> Tuple[str, Optional[str]]:
        """
        사용자 메시지를 처리하고 (응답_텍스트, output_file_path | None)을 반환한다.
        """
        raw_history = self._store.load_history(user_id, limit=self.MAX_HISTORY)
        history = [{"role": h["role"], "content": _to_api_content(h["content"])} for h in raw_history]
        history.append({"role": "user", "content": text})

        output_file: str | None = None
        response = None

        for _ in range(self.MAX_TOOL_ROUNDS):
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,
                messages=history,
            )

            assistant_content = [
                b.model_dump() if hasattr(b, "model_dump") else b
                for b in response.content
            ]
            history.append({"role": "assistant", "content": assistant_content})

            if response.stop_reason == "end_turn":
                break

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if getattr(block, "type", None) == "tool_use":
                        exec_result = execute_tool(block.name, block.input)
                        if exec_result.get("output_file"):
                            output_file = exec_result["output_file"]
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(exec_result["data"], ensure_ascii=False),
                        })
                history.append({"role": "user", "content": tool_results})
                continue

            break

        final_text = ""
        if response:
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    final_text += block.text

        self._store.append(user_id, "user", text)
        self._store.append(user_id, "assistant", final_text or "(완료)")

        return final_text, output_file

    def clear_history(self, user_id: str) -> None:
        self._store.clear(user_id)
