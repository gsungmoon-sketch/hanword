# 보안 정책 / Security policy

## 취약점 신고 / Reporting
공개 이슈 대신 GitHub **Security Advisories (Private vulnerability reporting)** 로 알려 주세요:
https://github.com/gsungmoon-sketch/hanword/security/advisories/new — 재현 방법과 영향 범위를 적어 주시면 확인 후 답변드립니다.
Please report privately via the link above, not in public issues.

## 설계상 보안 경계 / Security model
- **로컬 모드(기본)에는 로그인이 없습니다.** 포트에 닿는 누구나 문서 폴더를 읽고 쓰고 지울 수 있으므로 기본 바인드는
  `127.0.0.1` 이며, 루프백이 아닌 주소는 `WP_PUBLIC=1` 또는 `WP_ALLOW_REMOTE=1` 없이는 거부합니다.
  *Local mode has no authentication; non-loopback binds are refused unless explicitly allowed.*
- DNS 리바인딩 차단: 로컬 모드는 Host 헤더가 루프백/`WP_ALLOWED_HOSTS` 일 때만 응답(그 외 421).
- 교차 출처 POST 차단(Origin 검사, 403), 요청마다 nonce 를 쓰는 CSP, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`.
- 요청 본문 64 MB 상한, 동시 변환 상한(`WP_CONV_MAX`, 초과 시 503), 소켓 시간 제한.
- HWPX/DOCX 는 표준 라이브러리 expat 로 파싱하며 DTD/엔티티 선언·압축 폭탄·경로 조작을 거부합니다. 링크는 허용된 스킴만 남깁니다.
- 문서 이름은 안전한 문자만 남겨 문서 폴더 밖으로 나갈 수 없습니다.
- 디버그 브리지(`WP_DEBUG=1`)는 기본 꺼짐, 공개 모드에서는 항상 꺼짐.
- `.hwp` 변환용 pyhwp 등 선택 도구는 별도 프로세스로 실행됩니다.

## 공개 운영 체크리스트 / Running on the internet
1. `WP_PUBLIC=1` (서버 저장 없음, 무상태 변환만) + HTTPS 리버스 프록시(nginx, Caddy 등) 뒤에서 `127.0.0.1` 에 바인드.
2. `WP_PUBLIC_HOST=<도메인>` 으로 허용 Origin 지정, 필요하면 `WP_SITE_URL`.
3. 익명 게시판(`WP_BOARD_ENABLE=1`)을 켜면 `WP_BOARD_ADMIN` 에 긴 무작위 키를 두고 스팸을 감시하세요.
4. 프록시에서 요청 크기·속도 제한을 거세요.

## 알아 둘 한계 / Known limits
- 로컬 모드의 문서는 같은 컴퓨터의 **다른 OS 사용자**도 `127.0.0.1:8088` 로 접근할 수 있습니다. 여러 사람이 쓰는 컴퓨터에서는
  설치형 서비스 대신 각자 `hanword serve --port <각자 포트>` 로 쓰거나 운영체제 방화벽으로 막으세요.
  *Any local OS user can reach the loopback port; on shared machines run per-user instances.*
- 공개 모드의 자원 제한(동시 연결 수, 요청 속도)은 리버스 프록시에서 거세요. 본문 상한은 `WP_MAX_BODY`(기본 64 MB).
- `WP_PDF_LOCAL=1`(선택)은 신뢰할 수 없는 문서를 Chromium 으로 렌더링합니다(JavaScript 끔, 외부 요청 차단). 공개 서버에서는 꼭 필요할 때만 켜세요.
