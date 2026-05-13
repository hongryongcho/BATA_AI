# BATAGOTA AI Agent Project

> **B**uilding **A**utonomous **T**ask **A**gent for **G**eneral **O**peration, **T**racking & **A**utomation

## 프로젝트 개요

개인 AI 에이전트 시스템으로, 프로젝트 관리 / 외부 메시징 / MQTT 모니터링 / 기술 트렌드 리포팅을 통합한 자동화 허브입니다.

---

## 주요 기능

| 모듈 | 기능 |
|------|------|
| **Core Agent** | Claude API 기반 AI 추론 엔진, 대화 맥락 유지, 도구 호출 조율 |
| **Telegram Interface** | 외부에서 텔레그램으로 에이전트 접근, 명령 실행, 파일 송수신 |
| **KakaoTalk Interface** | 카카오 알림톡 / 챗봇 연동 (비즈니스 채널 필요) |
| **Google Drive** | 자료 업로드/다운로드, 프로젝트 파일 동기화 |
| **MQTT Broker** | Mosquitto 기반 브로커, 외부 장치 메시지 수신/발신 |
| **MQTT Monitor** | 실시간 페이로드 분석, 에러 패턴 탐지, 문자/텔레그램 알람 |
| **Tech Monitor** | 주기적 인터넷 기술 현황 수집 및 자동 리포트 생성 |
| **Project Manager** | 내부 프로젝트 생성/수정/추적, 진행상황 요약 |

---

## 시스템 아키텍처

```
외부 접근
  ├── Telegram Bot ──────────┐
  ├── KakaoTalk (알림톡) ────┤
  └── Google Drive ──────────┤
                             ▼
                    [Core Agent - Claude API]
                    ├── Memory (대화 기록)
                    ├── Tool Router (도구 선택)
                    └── Project Manager
                             │
          ┌──────────────────┼──────────────────┐
          ▼                  ▼                  ▼
    [MQTT Module]    [Tech Monitor]    [File/Drive Module]
    ├── Broker        ├── 웹 크롤링     ├── 로컬 파일 관리
    ├── 실시간 모니터  ├── 리포트 생성   └── Google Drive 동기화
    └── 에러 알람     └── 주기 실행
```

---

## 기술 스택

- **AI**: Anthropic Claude API (claude-3-5-sonnet)
- **Framework**: Python 3.11+, LangChain / 직접 구현
- **Messaging**: python-telegram-bot, Kakao Developers API
- **MQTT**: Mosquitto Broker, paho-mqtt
- **Storage**: Google Drive API v3, google-auth
- **Monitoring**: BeautifulSoup4, feedparser (RSS)
- **Scheduler**: APScheduler (주기 작업)
- **SMS 알람**: Twilio 또는 네이버 클라우드 SMS

---

## 환경 계획

| 단계 | 환경 | 시기 |
|------|------|------|
| Phase 1 (현재) | Windows 노트북 (테스트) | 즉시 |
| Phase 2 | Mac Mini 16GB / 512GB (안정화) | 다음달 |

---

## 디렉토리 구조

```
00_BATAGOTA/
├── core/               # AI 에이전트 핵심 로직
│   ├── agent/          # 에이전트 실행, 도구 라우팅
│   ├── memory/         # 대화 기록, 컨텍스트 관리
│   └── tools/          # 커스텀 도구 정의
├── interfaces/         # 외부 접근 채널
│   ├── telegram/       # 텔레그램 봇
│   ├── kakao/          # 카카오 채널
│   └── google_drive/   # 구글 드라이브 연동
├── mqtt/               # MQTT 관련
│   ├── broker_config/  # Mosquitto 설정
│   ├── monitor/        # 실시간 모니터링
│   └── alerts/         # 알람 로직
├── projects/           # 관리 대상 프로젝트들
│   └── _template/      # 신규 프로젝트 템플릿
├── monitoring/         # 기술 현황 모니터링
│   ├── tech_trends/    # 크롤러, RSS 수집
│   └── reports/        # 생성된 리포트
├── config/             # 설정 파일 (API키 등)
├── logs/               # 실행 로그
├── scripts/            # 유틸리티 스크립트
└── docs/               # 문서
```

---

## 시작 방법

→ [docs/SETUP.md](docs/SETUP.md) 참고

---

## 개발 로드맵

→ [docs/ROADMAP.md](docs/ROADMAP.md) 참고

## MQTT App Dashboard

→ [docs/MQTT_APP_DASHBOARD.md](docs/MQTT_APP_DASHBOARD.md) 참고
