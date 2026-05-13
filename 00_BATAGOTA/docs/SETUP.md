# 환경 설정 가이드

## 1. Python 버전 확인

```bash
python --version   # 3.11 이상 권장
```

## 2. 가상환경 생성 및 활성화

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Mac (Phase 2)
python -m venv .venv
source .venv/bin/activate
```

## 3. 패키지 설치

```bash
pip install -r requirements.txt
```

## 4. 환경변수 설정

```bash
# config/.env.example 파일을 복사해서 사용
copy config\.env.example config\.env
```

`.env` 파일에 실제 키 값 입력:
```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
GOOGLE_CREDENTIALS_PATH=config/google_credentials.json
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
```

## 5. 에이전트 실행 (CLI 테스트)

```bash
python core/agent/main.py
```

## 6. Telegram 봇 실행

```bash
python interfaces/telegram/bot.py
```

## 7. MQTT 브로커 실행 (Mosquitto 설치 후)

```bash
mosquitto -c mqtt/broker_config/mosquitto.conf
```

---

## 필수 설치 항목 (Windows)

1. **Python 3.11+**: https://python.org
2. **Mosquitto MQTT Broker**: https://mosquitto.org/download/
3. **VS Code** (이미 사용 중)
4. **Git** (버전 관리용)

---

## Anthropic API Key 발급

1. https://console.anthropic.com 접속
2. 회원가입 / 로그인
3. API Keys 메뉴 → Create Key
4. 발급된 키를 `.env`에 저장

---

## Telegram Bot Token 발급

1. 텔레그램 앱에서 `@BotFather` 검색
2. `/newbot` 명령 입력
3. 봇 이름 및 username 설정
4. 발급된 Token을 `.env`에 저장
