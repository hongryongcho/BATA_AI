# 메시지 계약서 (입력/출력/상태코드)

## 1. 입력 계약

### 1.1 사용자 -> 텔레그램 인터페이스
- 형태: 텍스트 명령 또는 자연어
- 예시
  - /data_report stock monthly graph
  - 지난달 엔비디아와 애플 그래프 올려줘

### 1.2 텔레그램 -> 관리자 라우터
- 함수: route_intent(intent, params, auto_upload)
- 필드
  - intent: string (필수)
  - params: object (선택, 기본 {})
  - auto_upload: bool (선택, 기본 true)

## 2. 내부 실행 계약

### 2.1 Manager -> Section Manager
- 입력
  - handler_name: string
  - intent: string
  - params: object

### 2.2 Section Manager -> Deputy
- 입력
  - handler_name: string
  - intent: string
  - params: object

### 2.3 Deputy -> Handler
- handler_name별 라우터 호출
  - mqtt_handler -> mqtt_router(intent, params)
  - generic_data_handler -> generic_router(intent, params)
  - stock_handler -> stock_router(intent, params)

## 3. 출력 계약

### 3.1 표준 응답
```json
{
  "status": "success|error|not_implemented",
  "intent": "string",
  "result": {},
  "output_file": "string, optional",
  "output_type": "string, optional",
  "drive_link": "string, optional",
  "file_id": "string, optional",
  "drive_upload_error": "string, optional",
  "org_trace": {
    "manager": "manager_agent",
    "section_manager": "*_section_manager",
    "deputy": "*_deputy_executor",
    "handler": "*_handler",
    "project": "string",
    "priority": "low|normal|high",
    "executed_at": "ISO8601 UTC"
  }
}
```

### 3.2 하위 호환 규칙
- 기존 소비자(telegram formatter)가 사용하던 result 중첩 구조를 유지한다.
- output_file/output_type 필드는 최상위에 유지한다.

## 4. 상태 코드 정의
- success
  - 정상 완료
- error
  - 라우팅 불가, 실행 실패, 파라미터 오류
- not_implemented
  - 경로는 정의되었으나 기능 미구현

## 5. 오류 메시지 규약
- 사람 읽기 가능한 단문 영어/한글 병행 허용
- 예시
  - Unknown intent: xxx
  - Unknown handler: xxx
  - limit must be in range 1..100
