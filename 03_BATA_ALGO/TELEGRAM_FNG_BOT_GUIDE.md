# 🤖 FnG 투자 정보 텔레그램 봇 설정 가이드

## 1️⃣ 현재 상태
```
✅ 봇 이름: @BataFnG_bot
✅ 봇 ID: 8821934889
✅ 봇 상태: 정상 작동
⏳ 상태: Chat ID 대기 중
```

## 2️⃣ Chat ID 획득 절차

### 방법 A: 기존 생성한 단체방 사용 (추천)

1. **텔레그램에서 생성한 FnG 단체방 오픈**
2. **봇 초대**
   - 그룹 정보 → 멤버 추가 → `@BataFnG_bot` 검색 후 추가

3. **봇에 명령 입력**
   ```
   /start    # 봇 시작
   /chatid   # Chat ID 확인
   ```

4. **Chat ID 복사**
   - 봇이 보내는 메시지에서 `Chat ID: -1001234567890` 형태 복사

5. **`.env` 파일 수정**
   ```env
   TELEGRAM_FNG_BOT_TOKEN=8821934889:AAE0aKQ5T2B378Mc71hp950VkM20lwO9If0
   TELEGRAM_FNG_CHAT_ID=-1001234567890  # ← 복사한 Chat ID
   ```

### 방법 B: 새로운 그룹 생성

```bash
# 터미널에서 주기적으로 실행해 Chat ID 캡처
python3 test_telegram_fng_bot.py
```

## 3️⃣ 구성 요소

### 파일 위치
```
03_BATA_ALGO/
├── telegram_fng_bot.py           # 메인 봇 클래스
├── test_telegram_fng_bot.py      # 테스트 & Chat ID 획득
├── integration_telegram_fng.py   # 매매 신호 통합 (작성 예정)
└── .env                          # 환경 설정
```

### 봇 기능
| 명령어 | 기능 |
|--------|------|
| `/start` | 봇 시작, 사용자 정보 등록 |
| `/chatid` | 현재 채팅방 Chat ID 확인 |
| `/test` | 테스트 메시지 전송 |

## 4️⃣ 메시지 형식

### BUY 신호 예시
```
🟢 BUY 신호 - TQQQ
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 RSI(2): 12.50
😨 Fear & Greed: 18/100 (Extreme Fear 😱)
💵 현재가: $75.32
🛒 매수기준가: $74.50

⏰ 2026-05-18 09:30:00 (Eastern)
```

### SELL 신호 예시
```
🔴 SELL 신호 - SOXL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 RSI(2): 82.30
😨 Fear & Greed: 78/100 (Greed 🤑)
💵 현재가: $45.80
💰 매도기준가: $46.20

⏰ 2026-05-18 10:15:00 (Eastern)
```

## 5️⃣ 다음 단계

1. **Chat ID 설정** → `.env` 파일 업데이트
2. **연동 테스트** → 샘플 메시지 전송
3. **자동화 연동** → `create_rsi_fng_sheet.py` 와 통합
4. **스케줄러 연동** → `scheduler_market_close.py` 트리거 시 자동 발송

---

## 📌 빠른 시작

```bash
# 1. 테스트 실행 (Chat ID 없어도 봇 연결 확인)
cd /Users/batagota/BATAGOTA/10_AI_BATA/03_BATA_ALGO
python3 test_telegram_fng_bot.py

# 2. Chat ID 획득 후 .env 수정
# TELEGRAM_FNG_CHAT_ID=-1001234567890

# 3. 봇 폴링 시작 (선택)
python3 telegram_fng_bot.py
```
