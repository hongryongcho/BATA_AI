# BATA Schedule

학교 시간표와 생활 알림을 관리하는 독립 웹 서비스입니다.

## Local development

```bash
cd 10_AI_BATA/06_BATA_SCHEDULE
uvicorn backend:app --host 127.0.0.1 --port 8790
```

브라우저에서 <http://127.0.0.1:8790>을 엽니다.

시간표와 생활 알림은 SQLite에 저장하며, Service Worker와 Web Push로 브라우저가 닫혀 있어도 알림을 받을 수 있습니다. 최초 접속 시 알림 권한을 허용해야 합니다.

Mac 서버에서는 알람 시 `afplay`로 로컬 MP3도 함께 재생합니다. 따라서 브라우저가 완전히 닫혀 있어도 서버에 연결된 스피커에서 수업 시작·종료 종소리가 출력됩니다. 휴대폰이나 다른 PC에서 같은 음원을 출력하려면 해당 기기에 별도 네이티브 수신 앱이 필요합니다.

브라우저 화면의 알람 감시와 소리 재생은 사용하지 않으며, 테스트 버튼도 Mac mini 서버의 `/api/sounds/test`를 호출합니다. Web Push 표시는 `silent`로 전달되어 노트북에서 알림음이 나지 않습니다.

Web Push를 활성화하려면 VAPID 키를 환경변수로 설정합니다.

```bash
export VAPID_PUBLIC_KEY=...
export VAPID_PRIVATE_KEY=...
export VAPID_EMAIL=mailto:admin@batagota.com
```

개발 환경에서는 첫 실행 시 `data/vapid_private.pem`과 `data/vapid_public.pem`을 생성해도 됩니다. 해당 키와 SQLite DB는 저장소에 커밋하지 않습니다.

## Domain

Cloudflare Tunnel은 `http://127.0.0.1:8790` origin으로 `schedule.batagota.com`에 연결되어 있습니다.

## Sound sources

- 수업 시작: 서울교육 아카이브 item 1843, Westminster Chimes
- 수업 종료: 서울교육 아카이브 item 1847, Canon
- 일반 알림: 서울교육 아카이브 item 1860, 쉬는시간 종소리5

원본 페이지: https://bbarchives.sen.go.kr/items/show/1843, https://bbarchives.sen.go.kr/items/show/1847, https://bbarchives.sen.go.kr/items/show/1860
