# CHANGELOG

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
