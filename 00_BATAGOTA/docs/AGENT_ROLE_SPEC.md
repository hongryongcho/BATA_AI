# Agent 역할 정의서 (과장/대리 구조)

## 1. 목표
- 요청을 단일 핸들러에서 직접 실행하지 않고,
- 관리자 Agent가 과장 Agent에 분배하고,
- 과장 Agent가 대리 Agent에게 실행을 위임하는 구조를 표준화한다.

## 2. 조직 구조
- Manager Agent (관리자)
  - 책임: intent 분류 결과를 routing 규칙에 따라 적절한 과장에게 배분
  - 출력: 실행 결과 + org_trace
- Section Manager (과장)
  - 책임: 도메인 정책 적용, 대리 선택, 실패 시 에러 전달
  - 예시: mqtt_section_manager, data_section_manager, stock_section_manager
- Deputy Executor (대리)
  - 책임: 실제 핸들러 호출 및 결과 반환
  - 예시: mqtt_deputy_executor, data_deputy_executor, stock_deputy_executor

## 3. 도메인별 책임 매핑
- MQTT 도메인
  - 과장: mqtt_section_manager
  - 대리: mqtt_deputy_executor
  - 실행 핸들러: mqtt_handler
- 데이터 리포트 도메인
  - 과장: data_section_manager
  - 대리: data_deputy_executor
  - 실행 핸들러: generic_data_handler
- 주식 특화 도메인
  - 과장: stock_section_manager
  - 대리: stock_deputy_executor
  - 실행 핸들러: stock_handler

## 4. 실행 원칙
- 모든 실행 결과는 org_trace를 포함한다.
- org_trace는 최소 아래 항목을 가진다.
  - manager
  - section_manager
  - deputy
  - handler
  - project
  - priority
  - executed_at (UTC)
- 기존 응답 포맷(status, intent, result, output_file)은 유지해 하위 호환성을 보장한다.

## 5. 장애 처리 원칙
- intent 미정의: Manager 단계에서 error 반환
- handler 미매핑: Manager 단계에서 error 반환
- handler 내부 예외: Deputy 결과의 error를 상위로 전달

## 6. 확장 원칙
- 신규 도메인 추가 시 순서
  1) routing.json에 intent/handler 등록
  2) Section Manager 매핑 추가
  3) Deputy 실행 분기 추가
  4) org_trace 점검
