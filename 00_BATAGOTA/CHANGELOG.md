# CHANGELOG

## 2026-05-13

### 01_BATA_STOCK — 가격 알림·리포트 서비스 개선
- `priceAlertService.js`
  - 텔레그램 채널 분리: `getMajorChatConfig()` (주요 종목) / `getEtfChatConfig()` (3배 ETF 전용)
    - 환경 변수: `TELEGRAM_MAJOR_BOT_TOKEN`, `TELEGRAM_MAJOR_CHAT_ID`, `TELEGRAM_ETF_BOT_TOKEN`, `TELEGRAM_ETF_CHAT_ID`
  - `parseThresholds()` 공통화 → `parseMajorThresholds()` (1.5/3/5/10/15%) / `parseEtfThresholds()` (5/10/15%)
  - 알림 포맷 개선: 개별 메시지 → 배치 통합 메시지 (`buildBatchAlertText()`)
    - NY 시각 포함, 상승/하락 분리 출력, 트리거 임계값 표시
- `telegramReportService.js`
  - `MONITOR_ASSETS` 에 3배 레버리지 ETF 23종 추가
    - TQQQ, SOXL, TECL, BULS, UPRO, HIBL, TNA, UDOW, MIDU, GDXU, DUSL, WEBL, LABU, WANT, DFEN, PILL, FAS, CURE, TPOR, DPT, UTSL, NAIL, RETL, TMF
  - `ETF_3X_CODES` Set export (priceAlertService 에서 ETF 분기 판별용)
  - `formatRowByColumns()` 컬럼 너비 고정 (ticker 6 / value 12 / metric 10)
  - `formatCloseSection()` 파라미터 `dateLabel` → `title` 로 범용화
- `marketService.js`
  - `getDailyMarketSummary()` `skipNewsCache` 파라미터 추가 — 뉴스 항상 새로 fetch
- 구 캐시 파일 정리: `daily-summary-v6-2026-05-08.json`, `daily-summary-v7-2026-05-08.json`, `daily-summary-v7-2026-05-11.json` 삭제

### 00_BATAGOTA — HMI 앱 서버 UI 보완
- `interfaces/app_server/web/app.js`
  - `updateMachineDisplay()`: `opTitleMachine`, `opTitleTopic` 엘리먼트 null 안전 업데이트 추가
  - `updateOperationTab()`: `opTitleRecipe`, `opTitleState` 엘리먼트 바인딩 추가, `opLastRx` null 체크
- `interfaces/app_server/web/index.html` / `style_new.css`
  - 운영 탭 타이틀 영역 UI 구조·스타일 추가

### ops/macos — macOS 런치에이전트/데몬 운영 스크립트 신규 추가
- `install_launchagents.sh` / `uninstall_launchagents.sh`
- `install_launchdaemons.sh` / `uninstall_launchdaemons.sh`
- `check_services.sh` — 서비스 상태 일괄 확인
- `set_server_power.sh` — 서버 전원 제어
- `README.md` — macOS 운영 가이드

---

## 2026-05-11
- HMI 웹 UI 3열 레이아웃 정리 및 중복 렌더링 이슈 수정
- `interfaces/app_server/web/index.html`
  - 헤더에서 `style_new.css` 로드
  - 중복으로 남아 있던 이전 레이아웃 블록 제거
  - 단일 3열 구조(좌측 네비/중앙 콘텐츠/우측 액션)만 유지
- `interfaces/app_server/web/style_new.css`
  - 3열 기반 레이아웃 스타일 신규 작성
  - 패널 폭/스크롤/게이지/상태 박스 스타일 정리
- `interfaces/app_server/web/app.js`
  - 하단 레거시 코드 정리
  - 제거된 UI API 참조로 인한 오류 발생 구간 제거
- 검증
  - 정적 오류 검사: `index.html`, `style_new.css`, `app.js` 오류 없음
  - 화면 구조: 좌/중/우 패널 정상 렌더링 확인
