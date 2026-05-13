# 현재 코드 기준 최소 변경 파일 목록

## A. 필수 코드 변경
- core/agent/org_hierarchy.py
  - 관리자/과장/대리 실행 계층 신설
- core/agent/main.py
  - 기존 직접 핸들러 호출 -> ManagerAgent 위임 방식으로 전환

## B. 필수 설계 문서
- docs/AGENT_ROLE_SPEC.md
  - 과장/대리 역할 정의서
- docs/MESSAGE_CONTRACT.md
  - 메시지 계약서(입력/출력/상태코드)

## C. 선택 확장(다음 단계)
- config/routing.json
  - 신규 도메인 intent 및 핸들러 등록 시 확장
- core/agent/llm_intent_router.py
  - 신규 도메인 자연어 규칙/검증 추가
- interfaces/telegram/bot.py
  - 신규 도메인 고정 명령어 추가
