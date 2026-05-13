# 개발 로드맵

## Phase 1 — 기반 구축 (현재 노트북, Windows)

### Step 1-1: 환경 준비 (1주)
- [ ] Python 3.11 설치 확인
- [ ] 가상환경 생성 (`venv`)
- [ ] Anthropic API Key 발급
- [ ] `requirements.txt` 기반 패키지 설치
- [ ] `.env` 파일로 키 관리 구조 설정

### Step 1-2: Core Agent 구현 (1~2주)
- [ ] Claude API 직접 호출 래퍼 작성
- [ ] 간단한 대화 메모리 (파일 or SQLite)
- [ ] Tool calling 구조 설계 (함수 등록 방식)
- [ ] CLI로 에이전트 대화 테스트

### Step 1-3: Telegram 봇 연동 (1주)
- [ ] Telegram Bot Token 발급 (BotFather)
- [ ] python-telegram-bot 세팅
- [ ] 메시지 수신 → 에이전트 → 응답 반환 파이프라인
- [ ] 파일 업로드/다운로드 기능
- [ ] **이 단계 완료 시: 폰에서 텔레그램으로 AI에이전트 제어 가능**

### Step 1-4: Project Manager 기능 (1주)
- [ ] 프로젝트 생성/조회/수정 도구
- [ ] Markdown 기반 프로젝트 문서 관리
- [ ] 진행 상황 요약 리포트 생성
- [ ] 텔레그램에서 "프로젝트 현황 알려줘" 명령 동작

### Step 1-5: MQTT 모듈 (1~2주)
- [ ] Mosquitto 브로커 설치 및 설정
- [ ] paho-mqtt로 subscribe/publish 래퍼
- [ ] 실시간 페이로드 파싱 및 로그
- [ ] 에러 패턴 정의 (임계값, 키워드)
- [ ] 텔레그램 알람 발송 연동

### Step 1-6: Google Drive 연동 (1주)
- [ ] Google Cloud Console 프로젝트 생성
- [ ] Drive API v3 OAuth 인증 설정
- [ ] 파일 업로드/다운로드/목록 조회 도구
- [ ] 텔레그램에서 드라이브 파일 조회 명령

### Step 1-7: Tech Trend Monitor (1주)
- [ ] 모니터링 대상 RSS/뉴스 소스 목록 정의
- [ ] feedparser로 RSS 수집
- [ ] Claude로 내용 요약 및 분류
- [ ] 주 1회 자동 리포트 생성 → 텔레그램 전송
- [ ] APScheduler로 주기 실행 설정

---

## Phase 2 — Mac Mini 이전 및 안정화

### Step 2-1: Mac 환경 세팅
- [ ] Python 환경 재구성 (pyenv 권장)
- [ ] 서비스 데몬화 (launchd 또는 supervisor)
- [ ] MQTT 브로커 상시 실행
- [ ] 에이전트 상시 실행 (백그라운드 서비스)

### Step 2-2: KakaoTalk 연동 (선택)
> ⚠️ 카카오 챗봇은 카카오 비즈니스 채널 승인 필요, 개인 계정은 제한적
- [ ] 카카오 알림톡 API (단방향 알람용) 검토
- [ ] 또는 카카오 i 오픈빌더 챗봇 구성
- [ ] 텔레그램이 안정화된 후 추가 고려

### Step 2-3: 고도화
- [ ] 벡터 DB 기반 장기 메모리 (ChromaDB 또는 Qdrant)
- [ ] RAG로 프로젝트 문서 Q&A
- [ ] 웹 UI 대시보드 (FastAPI + 간단한 HTML)
- [ ] SMS 알람 (네이버 클라우드 or Twilio)

---

## 우선순위 결정 가이드

```
빠른 체감 효과 순서:
1. Core Agent + CLI       → AI랑 대화 가능
2. Telegram 봇            → 폰에서 제어 가능 ★★★
3. Project Manager        → 실무 활용 시작
4. MQTT Monitor           → 현재 ESP32 프로젝트 연계
5. Google Drive           → 파일 워크플로우
6. Tech Trend             → 자동 인사이트
7. KakaoTalk              → 텔레그램 안정화 후
```

---

## 필요한 계정/키 목록

| 항목 | 용도 | 발급처 |
|------|------|--------|
| Anthropic API Key | Claude AI 호출 | console.anthropic.com |
| Telegram Bot Token | 봇 생성 | t.me/BotFather |
| Google OAuth 자격증명 | Drive API | console.cloud.google.com |
| Mosquitto | MQTT 브로커 (로컬 설치) | mosquitto.org |
| Twilio or NCloud SMS | 문자 알람 | twilio.com or ncloud.com |

---

## 참고: 카카오 vs 텔레그램

| 항목 | 텔레그램 | 카카오 |
|------|----------|--------|
| 개인 봇 생성 | 무료, 즉시 가능 | 비즈니스 채널 필요 |
| API 접근성 | 매우 좋음 | 제한적 |
| 국내 사용성 | 약간 낮음 | 높음 |
| 추천 | **Phase 1 메인** | Phase 2 알람용 고려 |
