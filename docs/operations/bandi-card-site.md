# 영호 가챠 사이트 운영 가이드

## Railway 구성

별도 업로드나 저장소 분리는 필요 없다. 기존 반디봇 서비스는 계속 이 GitHub 저장소의 `master`를 자동 배포한다. 같은 Railway 프로젝트에 웹 서비스 하나와 PostgreSQL 하나만 추가하고, 웹 서비스도 같은 저장소의 `master`를 소스로 연결한다.

Railway의 기존 `railway.json` Config as Code는 신규 서비스에서 사용할 수 없으므로 서비스 설정에서 다음 값을 한 번 지정한다.

1. PostgreSQL을 추가한다.
2. 새 웹 서비스에 이 저장소의 `master`를 연결한다.
3. 웹 서비스 변수에 `RAILWAY_DOCKERFILE_PATH=Dockerfile.web`을 설정한다.
4. 웹 서비스의 Healthcheck Path를 `/api/health`, replica 수를 `1`로 설정한다. Dockerfile의 기본 시작 명령이 Alembic 마이그레이션 후 FastAPI를 실행하므로 Custom Start Command는 비워 둔다.
5. 웹과 기존 반디봇 서비스가 PostgreSQL의 같은 `DATABASE_URL`을 참조하게 한다.
6. 웹 도메인을 만든 뒤 `CARD_SITE_URL`과 `DISCORD_REDIRECT_URI=https://도메인/api/auth/discord/callback`을 설정한다.
7. Discord Developer Portal의 OAuth2 Redirects에 같은 callback URL을 등록한다.

이후에는 `master`에 반영된 변경이 두 서비스에 각각 자동 배포되므로 코드를 따로 업로드하지 않는다. 웹은 실시간 거래의 연결 상태와 15초 재접속 유예를 프로세스 메모리에 보관하므로 replica 1개를 유지해야 한다. 동시에 여러 거래방을 사용하는 것은 가능하지만 웹 프로세스를 둘 이상 띄우는 것은 지원하지 않는다. 재배포나 재시작 시 미완료 거래는 취소되고 예약된 카드는 자동 반환된다.

## 환경 변수

공통:

- `DATABASE_URL`: 같은 Railway PostgreSQL 연결 문자열
- `CARD_SITE_URL`: 공개 HTTPS 주소
- `SPECIAL_USER_ID`: 관리자로 사용할 Discord snowflake ID

웹:

- `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, `DISCORD_REDIRECT_URI`
- `CARD_SESSION_SECRET`: 충분히 긴 무작위 문자열
- `CARD_SECURE_COOKIES=true`
- `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_NAME`, `S3_REGION`

봇:

- 기존 `DISCORD_BOT_TOKEN`, `OPENAI_API_KEY` 등
- 웹과 같은 `DATABASE_URL`, `CARD_SITE_URL`

Railway의 임시 파일 시스템에는 카드 이미지를 영구 보관하지 않는다. 운영에서는 R2, S3 등 S3 호환 저장소를 반드시 연결한다.

## 배포 전후 확인

배포 전:

```powershell
python -m pytest -q
Push-Location web
npm test
npm run build
Pop-Location
```

배포 후:

1. `/api/health`가 `{"status":"ok"}`를 반환하는지 확인한다.
2. Discord 로그인 후 최초 안내가 한 번만 노출되는지 확인한다.
3. 일반 사용자에게 관리 메뉴가 없고 `SPECIAL_USER_ID`만 관리 API에 접근 가능한지 확인한다.
4. 테스트 카드를 추가하고 이미지·등급 테두리·별·YP가 표시되는지 확인한다.
5. 두 계정으로 거래 초대, 더 요구하기, 양쪽 수락, 연결 단절 후 15초 이내 복구를 확인한다.
6. 봇 로그에서 알림 및 프로필 동기화 오류가 반복되지 않는지 확인한다.

## 운영 규칙

- 하루 기준은 `Asia/Seoul` 오전 5시부터 다음 날 오전 5시까지다.
- 뽑기 요청은 DB 고유 제약과 idempotency key로 중복 지급을 방지한다.
- 총 YP는 보유 수량이 아니라 보유 중인 서로 다른 카드 종류의 YP 합이다.
- 5성 공개 기록은 획득 시각, 최신 Discord 사용자명/표시 이름, 카드명으로 표시한다.
- OAuth 로그인 때 Discord 프로필이 즉시 갱신되며 반디봇이 서버 공유 여부와 무관하게 `Get User`로 오래된 프로필을 6시간 주기로 동기화한다.
- 카드 이미지 교체·영구 삭제 파일은 봇의 재시도 큐가 정리한다.

## 장애 대응

- 거래 중 웹 재시작: 시작 시 모든 미완료 거래를 취소하고 예약 수량을 반환한다. 사용자는 새 거래를 시작하면 된다.
- Discord DM 실패: 차단·존재하지 않는 사용자는 실패 처리한다. 일시 장애는 지수 백오프로 최대 6회 재시도한다. 카드 선물·거래 완료 자체는 롤백되지 않는다.
- 프로필 동기화 실패: 마지막 정상 프로필을 계속 표시하고 오류를 기록한 뒤 다음 주기에 재시도한다.
- 이미지 저장소 실패: DB 정리 큐에 남아 재시도된다. 카드 데이터 트랜잭션에는 영향을 주지 않는다.
- 마이그레이션 실패: 웹 컨테이너 시작 로그의 `alembic upgrade head` 오류를 확인한다. 실패한 인스턴스는 healthcheck를 통과하지 못하므로 원인을 수정한 뒤 재배포한다.

## Post-Deploy Monitoring & Validation

배포 후 첫 24시간은 운영자가 담당한다.

- Railway 웹 로그에서 `500`, `IntegrityError`, `WebSocket`, `trade`를 검색한다. 정상 상태는 `/api/health` 성공과 반복 예외가 없는 것이다.
- 봇 로그에서 `Card notification loop error`, `Discord profile sync error`, `Card image cleanup error`, `Card site housekeeping error`를 검색한다. 일시 오류는 재시도로 사라져야 하며 같은 오류가 3회 이상 연속 반복되면 실패 신호다.
- PostgreSQL에서 `notification_outbox`의 `pending/retry` 수와 가장 오래된 `available_at`, `image_cleanup`의 대기 건수, `trade_rooms`의 `reconnecting` 건수를 확인한다. 오래된 대기가 계속 증가하면 봇 서비스와 DB 연결을 점검한다.
- 두 테스트 계정으로 로그인, 뽑기 1회 제한, 선물 즉시 반영, 거래 완료, 사용자명 변경 동기화를 확인한다.
- 뽑기 중복 지급, 예약 수량 음수, 관리자 외 관리 API 접근이 확인되면 즉시 웹 서비스를 이전 배포로 롤백하고 DB는 보존한다. 스키마 롤백은 파괴적이므로 첫 배포 이후 데이터를 받은 상태에서는 실행하지 않는다.
