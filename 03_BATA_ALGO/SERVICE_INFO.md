# 🤖 FnG 자동 투자 시스템 - 서비스 정보

## ✅ 현재 상태 (2026-05-18 19:34 KST)

### 실행 중인 서비스
```
✅ FnG 스케줄러 데몬       (PID: 86052)
✅ 개인 개발 봇 데몬       (PID: 75981)
```

---

## 📅 자동 실행 일정

### 🟢 프리장 오픈 (매일 04:00 ET / 17:00 KST)
- **기능**: 현재값 기준 시뮬레이션
- **데이터**: 프리장 실시간 가격
- **출력**:
  - 구글시트 업데이트 (Summary 탭)
  - 텔레그램 알림 (FnG 봇)
  - 다음날 예약 주문 정보 제공

### 🔴 장마감 후 15분 (매일 16:30 ET / 05:30 KST+1)
- **기능**: 종가 기준 시뮬레이션 **[종가로 재계산]**
- **데이터**: 일일 종가 (Close Price)
- **출력**:
  - 구글시트 업데이트 (당일 최종 데이터)
  - 텔레그램 알림 (FnG 봇)
  - 일일 수익률, MDD, Sharpe Ratio 등 통계

---

## 🔧 서비스 관리

### 서비스 시작 (모든 데몬 활성화)
```bash
cd /Users/batagota/BATAGOTA/10_AI_BATA/03_BATA_ALGO
./start_services.sh start
```

### 서비스 상태 확인
```bash
./start_services.sh status
```

### 서비스 중지 (모든 데몬 종료)
```bash
./start_services.sh stop
```

### 서비스 재시작
```bash
./start_services.sh restart
```

---

## 📊 알고리즘 정보

### RSI2 + Fear & Greed 필터
```
매수 신호:
  • RSI(2) < 15 (과매도)
  • AND Fear & Greed < 90 (극도의 탐욕 제외)
  
매도 신호:
  • TQQQ: RSI(2) > 75 (과매수)
  • SOXL: RSI(2) > 90 (더 높은 기준)

최적 파라미터:
  • Fear Max: 35 이하 → 매도 허용
  • Greed Min: 90 이상 → 매수 금지
```

### 10년 성과 (2016-2026)
```
TQQQ: 212.21% (F&G 필터 적용)
SOXL: 35,537.21% (압도적 우위)
```

---

## 📱 Telegram 서비스

### FnG 정보 봇 (자동 알림)
```
채팅방: Bata FnG Info
토큰: TELEGRAM_FNG_BOT_TOKEN
채팅ID: -5012151690

일정:
  • 04:00 ET (프리장): 현재값 기준 알림
  • 16:30 ET (장마감): 종가 기준 알림 + 최종 통계
```

### 개인 개발 봇 (수동 명령)
```
사용자: @BataMain_Bot
토큰: TELEGRAM_PERSONAL_BOT_TOKEN

명령어:
  /start   - Chat ID 자동 등록
  /read <파일>  - 파일 내용 조회
  /run <명령>   - 셸 명령 실행
  /logs    - 최근 20줄 로그 조회
  /help    - 명령어 도움말
```

---

## 📂 로그 파일 위치

```
📊 스케줄러 로그:    ~/BATAGOTA/10_AI_BATA/03_BATA_ALGO/logs/scheduler_fng.log
🤖 개인 봇 로그:    ~/BATAGOTA/10_AI_BATA/03_BATA_ALGO/logs/personal_bot_daemon.log
📈 백테스트 결과:   Google Sheets (ID: 1WTyL9bYvAvai8CaOsZJ3vQoXVOxJEtFJvkiy_N8jtNM)
```

---

## 🎯 일일 운영 절차

```
매일 04:00 ET (프리장 오픈)
  ↓
  1️⃣ RSI2+F&G 시뮬레이션 (현재값 기준)
  2️⃣ 구글시트 업데이트
  3️⃣ 텔레그램 알림 (예약 주문 정보)
  ↓
맞춤 장중 거래
  ↓
매일 16:30 ET (장마감 후 15분)
  ↓
  1️⃣ RSI2+F&G 시뮬레이션 (종가 기준) [재계산]
  2️⃣ 구글시트 최종 업데이트
  3️⃣ 텔레그램 알림 (일일 통계 + 성과)
  ↓
다음날 준비
```

---

## 🚨 문제 해결

### 서비스가 실행 안 될 때
```bash
# 기존 프로세스 확인
ps aux | grep scheduler_market_close
ps aux | grep personal_bot

# 기존 프로세스 강제 종료 후 재시작
pkill -f scheduler_market_close
pkill -f personal_bot
./start_services.sh start
```

### 로그 확인
```bash
# 실시간 로그 모니터링
tail -f logs/scheduler_fng.log
tail -f logs/personal_bot_daemon.log

# 최근 30줄 로그
tail -30 logs/scheduler_fng.log
```

### 텔레그램 알림 테스트
```bash
# 강제 실행 (시간 무시, dry-run은 전송하지 않음)
python3 scheduler_market_close.py --once --force --dry-run
python3 scheduler_market_close.py --premarket-once --force
```

---

## 🔐 설정 파일 위치

```
.env 파일: ~/BATAGOTA/10_AI_BATA/03_BATA_ALGO/.env

주요 설정:
  • TELEGRAM_FNG_BOT_TOKEN=8821934889:...
  • TELEGRAM_FNG_CHAT_ID=-5012151690
  • TELEGRAM_PERSONAL_BOT_TOKEN=8768519593:...
  • SPREADSHEET_ID=1WTyL9bYvAvai8CaOsZJ3vQoXVOxJEtFJvkiy_N8jtNM
  • GOOGLE_CREDENTIALS_PATH=../02_BATA_MQTT/config/google_credentials.json
```

---

## 💡 팁

### 1. 데몬 계속 실행 유지
```bash
# macOS: launchd로 자동 시작 설정 (선택)
# 또는 cron 대신 daemon 모드 유지 (현재 설정)
```

### 2. 리모트 서버에서 실행
```bash
# SSH 연결 후 screen이나 tmux 사용
screen -S fng_scheduler
cd ~/BATAGOTA/10_AI_BATA/03_BATA_ALGO
./start_services.sh start

# Ctrl+A, D로 분리 (screen 유지)
```

### 3. 성능 모니터링
```bash
# 데몬 메모리 사용량 확인
ps -o pid,vsz,rss,comm | grep scheduler
ps -o pid,vsz,rss,comm | grep personal_bot
```

---

## ✨ 다음 단계

- [ ] 텔레그램에서 `/start` 명령으로 개인 봇 등록
- [ ] 매일 04:00 & 16:30 의 자동 알림 확인
- [ ] Google Sheets에서 실시간 거래 기록 확인
- [ ] 주 1회: 성과 분석 및 포트폴리오 조정

---

생성일: 2026-05-18 19:34 KST
마지막 업데이트: 2026-05-18
상태: ✅ 모든 서비스 정상 운영 중
