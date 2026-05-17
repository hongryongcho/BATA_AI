# -*- coding: utf-8 -*-
import json
import logging
import os
import re
from typing import Dict

import requests

_log = logging.getLogger(__name__)

_OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
_MODEL_NAME = os.getenv("OLLAMA_MODEL", "mistral")


def _normalize_summary_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                lines.append(text)
        return "\n".join(lines)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def _validate_ollama() -> bool:
    try:
        resp = requests.get(f"{_OLLAMA_API_URL}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def generate_summary(transcript: str) -> Dict[str, str]:
    """
    Ollama LLM to create detailed meeting minutes
    Returns: overview, details, tools, conclusion
    """
    if not transcript:
        return {
            "overview": "",
            "details": "",
            "tools": "",
            "conclusion": "",
        }

    if not _validate_ollama():
        raise RuntimeError(
            f"Cannot connect to Ollama at {_OLLAMA_API_URL}\n"
            "Please:\n"
            "1. Run 'brew services start ollama' or 'ollama serve'\n"
            "2. Download model: 'ollama pull mistral'\n"
            "3. Check port 11434 is open"
        )

    prompt = f"""다음은 회의 또는 강의의 녹음 전사입니다. 상세한 회의록 형식으로 정리하세요.

전사 내용:
{transcript}

---

⚠️ 매우 중요: 반드시 한국어로만 작성하세요. 절대로 영어로 작성하지 마세요.
⚠️ IMPORTANT: Write ONLY in Korean. NEVER use English.

회의록 정리 규칙 (매우 중요):
1) 한국어로만 작성 (필수)
2) 각 섹션별로 구체적인 내용, 숫자, 회사명, 제품명, 데이터를 반드시 포함
3) 불릿 포인트나 번호 매김으로 명확하게 구조화
4) 모호한 표현 대신 구체적이고 측정 가능한 내용 포함
5) **details는 가장 중요함** - 최대한 상세하고 풍부하게 작성

각 필드별 작성 기준:

**overview** (개요 및 배경)
- 회의의 목적, 배경, 주제를 명확히 설명 (2-3줄)
- "왜 이런 주제를 다루는가"의 맥락 포함
- 중요한 통계, 트렌드, 현황 언급

**details** (상세 내용 - 주요 항목별) ⭐ 매우 중요 ⭐
- 이 필드가 가장 중요한 필드입니다. 최대한 풍부하고 상세하게 작성하세요
- 최소 800자 이상으로 작성 (가능하면 1000자 이상)
- 전사 원문의 모든 중요한 포인트를 누락 없이 포함
- 주요 내용을 "1. 항목", "2. 항목", "[주차명]", "- 항목" 등으로 계층적으로 구분
- 각 항목별로:
  * 구체적인 내용과 설명 (최소 3-5줄 이상)
  * 회사명, 제품명, 기술명, 도구명, 숫자, 금액, URL 등 모든 구체적인 예시 포함
  * 과정, 단계, 방법론을 상세히 설명
  * 이유, 배경, 맥락도 함께 기술
  * 결과나 목표도 명확하게 기술
- 섹션 제목 사용: [1주차], [2주차], [학습 목표], [도구 소개] 등
- 서브항목 세분화: (1), (2), (3), (가), (나) 등으로 더 자세히
- 질의응답, 의견 교환, 중요한 논의 내용 포함
- 전사 원문에서 강조한 부분이나 반복된 부분도 중요하게 담기
- 수치, 데이터, 통계, 구체적인 사례 모두 포함

**tools** (핵심 기술 및 도구)
- 언급된 기술명, 도구명, 플랫폼, 서비스, 언어, 프레임워크 등
- 구체적인 제품명 (예: "Google Analytics", "Cursor", "Claude 3.5 Sonnet")
- 버전 정보나 구체적인 사용 방식도 기입
- 가능하면 분류 (개발 도구, 결제, 분석 등)

**conclusion** (주요 메시지 및 결론)
- 핵심적인 결론과 배운 점 (3-5줄)
- 향후 전략이나 비전
- 핵심 성공 요소나 주의사항
- "~은 수단일 뿐" 형태의 철학적 메시지도 포함

📋 결과 형식 예시:
- details: 
  "[1주차] 웹 개발 기초
  - IT 프로덕트 구조: 프론트엔드(화면)와 백엔드(서버/DB)...
  - HTML/CSS/JS: 세부 문법 암기보다...
  - Vibe Coding: AI(Cursor 등)를 활용해...
  
  [2주차] 유입과 성장
  - SEO/GEO 최적화: 구글 검색..."

JSON 형식 (모든 필드는 문자열, 줄바꿈 포함 가능):
{{
  "overview": "개요 및 배경",
  "details": "상세 내용 (여러 줄, 매우 구체적이고 풍부하게)",
  "tools": "기술 및 도구 목록",
  "conclusion": "주요 메시지 및 결론"
}}

JSON만 반환하세요 (한국어로):"""

    try:
        response = requests.post(
            f"{_OLLAMA_API_URL}/api/generate",
            json={
                "model": _MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "temperature": 0.3,
            },
            timeout=300,
        )
        response.raise_for_status()
        result = response.json()

        if "error" in result:
            _log.error("[llm_summary] Ollama error: %s", result["error"])
            raise RuntimeError(f"Ollama error: {result['error']}")

        response_text = result.get("response", "").strip()
        _log.info("[llm_summary] Response length: %d chars", len(response_text))
        _log.info("[llm_summary] Response text (first 500): %s", response_text[:500])

        if not response_text:
            _log.error("[llm_summary] Empty response from Ollama")
            raise RuntimeError("Ollama returned empty response")

        # Try to extract JSON
        json_text = response_text
        if "```json" in json_text:
            json_text = json_text.split("```json")[1].split("```")[0].strip()
        elif "```" in json_text:
            json_text = json_text.split("```")[1].split("```")[0].strip()

        # Try parsing
        try:
            summary = json.loads(json_text)
        except json.JSONDecodeError:
            # Try partial extraction
            start = json_text.find("{")
            end = json_text.rfind("}")
            if start >= 0 and end > start:
                try:
                    summary = json.loads(json_text[start:end+1])
                except json.JSONDecodeError:
                    # Fallback: extract fields with regex
                    summary = _extract_fields_regex(json_text)
            else:
                summary = _extract_fields_regex(json_text)

        result = {
            "overview": _normalize_summary_value(summary.get("overview", "")),
            "details": _normalize_summary_value(summary.get("details", "")),
            "tools": _normalize_summary_value(summary.get("tools", "")),
            "conclusion": _normalize_summary_value(summary.get("conclusion", "")),
        }
        _log.info("[llm_summary] Final summary (before return): %s", json.dumps(result, ensure_ascii=False)[:500])
        return result
    except Exception as e:
        _log.error("[llm_summary] Error: %s", str(e)[:100])
        raise RuntimeError(f"Summary failed: {str(e)}")


def _extract_fields_regex(text: str) -> Dict[str, str]:
    """Extract fields with regex as fallback"""
    result = {"overview": "", "details": "", "tools": "", "conclusion": ""}
    
    # Extract each field
    for field in ["overview", "details", "tools", "conclusion"]:
        pattern = f'"{field}"\\s*:\\s*"((?:[^"\\\\]|\\\\.)*?)"'
        match = re.search(pattern, text, re.DOTALL)
        if match:
            result[field] = match.group(1)
    
    return result
