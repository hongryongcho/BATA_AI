# MQTT App Dashboard

## 개요
- 머신 선택 버튼으로 원하는 Machine(M1~M999) 상태를 조회
- 최근 수신 메시지 위젯 표시
- 버튼 클릭으로 MQTT Publish(Command 토픽) 실행

## 실행
```bash
python scripts/run_mqtt_app_dashboard.py
```

기본 접속 주소:
- http://127.0.0.1:8787

## 주요 API
- `GET /api/machines`
- `GET /api/machine/{machine_no}/overview`
- `GET /api/machine/{machine_no}/recent?limit=40`
- `POST /api/machine/{machine_no}/publish`

## Publish 토픽 규칙
- Topic: `BAGO/M{machine_no}/Command`
- Payload:
```json
{
  "action": "START",
  "payload": {},
  "requested_at": "2026-05-11T00:00:00+00:00",
  "source": "batagota_app_server"
}
```

## 환경 변수
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- `SQLITE_PATH`
- `APP_SERVER_HOST` (default: 127.0.0.1)
- `APP_SERVER_PORT` (default: 8787)
