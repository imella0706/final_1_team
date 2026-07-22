# BrandMate Backend 구현 범위

이 문서는 현재 코드 기준의 백엔드 인증 구현 범위를 팀원이 빠르게 확인하기 위한 문서다. 상세 PRD가 아니라, 실제 구현된 L2 MVP 범위와 아직 배포 전에 확인해야 할 항목만 정리한다.

대상 애플리케이션은 `apps/api`와 `apps/web`이다. `visitor_flow_poc`, `web-legacy-ad-content`에는 회원가입/로그인 기능을 붙이지 않는다.

## Blunt Review

현재 인증 백엔드는 단순 JWT 문자열 발급 수준이 아니다. L2 MVP 기준으로 필요한 핵심 보안 경계는 대부분 구현되어 있다.

다만 코드 구현 완료와 공개 배포 완료는 다르다. 실제 SMTP 발신 도메인, HTTPS 브라우저 E2E, 약관 동의 요구사항은 로컬 코드만으로 증명할 수 없다. 이 3개는 배포 전 별도 확인이 필요하다.

## 구현 수준

| Level | 상태 | 판단 |
| --- | --- | --- |
| L1 POC | 완료 | 로컬 회원가입, 로그인, Refresh, 로그아웃 동작 |
| L2 MVP | 코드 완료, 배포 검증 일부 필요 | DB 기반 Refresh/session/rate limit, 이메일 인증, 비밀번호 재설정, 테스트 자동화 구현 |
| L3 Production | 미구현 | Redis 전환, 비대칭 키 rotation, OpenTelemetry, MFA, 관리자 감사 로그는 확장 단계 |

## 백엔드 흐름

```text
# [Design Intent] HTTP, business rule, persistence 책임을 단방향으로 분리한다.
apps/web/app.js
  -> FastAPI auth router
    -> AuthService
      -> AuthRepositoryPort
        -> SqlAlchemyAuthRepository
          -> AsyncSession
            -> PostgreSQL
```

역할은 아래처럼 나눈다.

- `router.py`: HTTP 요청/응답, Cookie, Origin 검증, rate limit 처리
- `service.py`: 이메일 정규화, 회원가입, 로그인, Refresh rotation, 로그아웃, 비밀번호 변경 규칙 처리
- `repository.py`: DB 조회, row lock, 저장, commit 처리
- `security.py`: Argon2id 비밀번호 해시, JWT 발급/검증, opaque token 생성
- `dependencies.py`: 보호 API의 현재 사용자/session 검증
- `rate_limit.py`: 로컬 memory 또는 운영 PostgreSQL rate limiter
- `outbox.py`: 이메일 인증/비밀번호 재설정 메일 발송 worker

Controller가 repository를 직접 호출하거나, Service가 SQLAlchemy 세션을 직접 다루는 구조는 금지한다. 계층은 파일을 늘리기 위한 장식이 아니라 변경 이유를 분리하기 위한 경계다.

## 구현된 인증 기능

| 기능 | 상태 | 설명 |
| --- | --- | --- |
| 회원가입 | 완료 | 이메일, 표시 이름, 비밀번호 기반 가입 |
| 로그인 | 완료 | 이메일을 로그인 ID로 사용 |
| 비밀번호 저장 | 완료 | 원문 저장 금지, Argon2id hash만 DB 저장 |
| Access JWT | 완료 | 기본 10분, `iss/aud/sub/sid/exp/iat/jti/typ/ver` 검증 |
| Refresh Token | 완료 | HttpOnly Cookie에 원문 저장, DB에는 SHA-256 hash 저장 |
| Refresh rotation | 완료 | Refresh마다 새 token 발급, 재사용 탐지 시 family 폐기 |
| 로그아웃 | 완료 | 현재 Refresh family 폐기 |
| 전체 로그아웃 | 완료 | `token_version` 증가로 기존 Access/Refresh 즉시 거부 |
| 특정 기기 해제 | 완료 | `sid` 기반 session 목록/개별 폐기 |
| 이메일 인증 | 완료 | 일회용 purpose-bound token, DB에는 hash만 저장 |
| 비밀번호 재설정 | 완료 | 재설정 후 모든 session/Refresh 폐기 |
| 보호 API | 완료 | Bearer Access Token 없으면 `401` |
| Rate limit | 완료 | 운영은 PostgreSQL 원자 카운터, local/test만 memory |
| Observability | 완료 | request log, auth event log, Prometheus text metric |

## API 계약

모든 API 경로의 prefix는 `/api/v1`이다.

| Method | Endpoint | 역할 |
| --- | --- | --- |
| `POST` | `/api/v1/auth/signup` | 회원가입 |
| `POST` | `/api/v1/auth/verify-email` | 이메일 인증 token 소비 |
| `POST` | `/api/v1/auth/verify-email/resend` | 인증 메일 재발송 |
| `POST` | `/api/v1/auth/login` | Access JWT 발급 + Refresh Cookie 설정 |
| `POST` | `/api/v1/auth/refresh` | Refresh rotation + 새 Access JWT 발급 |
| `POST` | `/api/v1/auth/logout` | 현재 로그인 family 폐기 |
| `POST` | `/api/v1/auth/logout-all` | 전체 Refresh/session 폐기 |
| `POST` | `/api/v1/auth/password-reset/request` | 비밀번호 재설정 메일 요청 |
| `POST` | `/api/v1/auth/password-reset/confirm` | 일회용 token으로 비밀번호 재설정 |
| `POST` | `/api/v1/auth/password/change` | 현재 비밀번호 확인 후 변경 |
| `GET` | `/api/v1/auth/sessions` | 로그인된 기기 목록 |
| `DELETE` | `/api/v1/auth/sessions/{session_id}` | 특정 기기 즉시 로그아웃 |
| `GET` | `/api/v1/auth/me` | 현재 사용자 조회 |

프런트는 오류 메시지 문자열을 파싱하지 말고 안정적인 `code` 값을 기준으로 분기한다. 대표 code는 `AUTH_INVALID_CREDENTIALS`, `AUTH_EMAIL_ALREADY_EXISTS`, `AUTH_EMAIL_NOT_VERIFIED`, `AUTH_TOKEN_EXPIRED`, `AUTH_SESSION_REVOKED`, `AUTH_RATE_LIMITED`다.

## DB 모델

| 테이블 | 역할 |
| --- | --- |
| `users` | 사용자 계정, 이메일, 표시 이름, password hash, 상태, token version |
| `refresh_tokens` | Refresh token hash, family, 만료, 사용/폐기 상태 |
| `auth_sessions` | 로그인 기기 session, `sid` 검증, 개별 기기 폐기 |
| `auth_action_tokens` | 이메일 인증/비밀번호 재설정용 일회용 token hash |
| `auth_outbox_events` | SMTP 메일 발송 작업, retry/backoff/dead-letter |
| `auth_rate_limit_buckets` | PostgreSQL 기반 rate limit 원자 카운터 |

이메일 중복 방어는 애플리케이션 사전 조회만 믿지 않는다. 최종 방어선은 `users.email_normalized`의 DB UNIQUE 제약이다.

## Token 저장 정책

브라우저 저장 정책은 아래와 같다.

- Access Token: JS 모듈 메모리에만 저장
- Refresh Token: HttpOnly Cookie에 저장
- `localStorage`: Access/Refresh Token 저장 금지
- `sessionStorage`: Access/Refresh Token 저장 금지

DB 저장 정책은 아래와 같다.

- 비밀번호 원문 저장 금지
- Refresh Token 원문 저장 금지
- 이메일 인증/비밀번호 재설정 token 원문 저장 금지
- JWT payload에 이메일, 비밀번호, 전화번호 같은 개인정보 저장 금지

비밀번호는 암호화가 아니라 Argon2id hash로 저장한다. 암호화는 복호화 가능성이 있고, 비밀번호 저장에는 맞지 않는다. 로그인 시 입력 비밀번호를 hash 검증 함수로 비교해서 맞는지만 판단한다.

## Rate Limit 결정

운영 API는 PostgreSQL UPSERT 원자 카운터로 rate limit을 공유한다.

인메모리 rate limit은 프로세스 재시작, 다중 worker, 다중 instance에서 제한 횟수가 갈라진다. 공개 배포용 보안 경계로 쓰면 안 된다. Redis를 바로 추가하지 않은 이유는 현재 L2 규모에서 PostgreSQL이 이미 필수 인프라이기 때문이다.

현재 정책은 아래와 같다.

| Scope | 제한 |
| --- | --- |
| 회원가입 | IP 기준 5회/5분 |
| 로그인 | IP 기준 50회/5분, 이메일 기준 10회/5분 |
| Refresh | IP 기준 30회/분 |
| 이메일 인증 재전송 | 이메일 기준 3회/15분 |
| 비밀번호 재설정 | 이메일 기준 3회/15분 |

운영 설정에서 `BRANDMATE_AUTH_RATE_LIMIT_BACKEND=postgres`가 아니면 서버 시작을 거부한다. local/test 환경만 `memory` backend를 허용한다. L3에서 DB write QPS가 실제 병목이 되면 `AuthRateLimiterPort` 뒤 구현만 Redis로 교체한다.

## 이메일 발송과 Outbox

회원가입 API는 외부 SMTP를 직접 동기 호출하지 않는다. 사용자, action token, outbox event를 같은 DB transaction으로 저장하고 빠르게 응답한다.

Outbox worker가 메일 발송을 담당한다.

- SMTP timeout 설정
- 지수 backoff와 jitter
- 최대 재시도 횟수
- dead-letter 상태
- raw token DB 저장 금지

SMTP 장애가 나도 회원가입 DB commit은 되돌리지 않는다. 외부 네트워크 호출을 DB transaction 안에 넣는 구현은 금지한다.

## 환경 변수 기준

운영 환경 예시는 `apps/api/.env.gcp.example`만 기준으로 관리한다. `env.example`은 업데이트하지 않는다.

인증 관련 핵심 값은 아래와 같다.

```text
# [Design Intent] 운영 인증 설정은 안전하지 않은 조합이면 서버 시작 단계에서 실패해야 한다.
BRANDMATE_ENVIRONMENT=production
BRANDMATE_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@PRIVATE_DB_HOST:5432/brandmate
BRANDMATE_AUTH_SECRET_KEY=replace-me
BRANDMATE_AUTH_REFRESH_COOKIE_NAME=__Host-brandmate_refresh
BRANDMATE_AUTH_REFRESH_COOKIE_SECURE=true
BRANDMATE_AUTH_EMAIL_VERIFICATION_REQUIRED=true
BRANDMATE_AUTH_EMAIL_DELIVERY_ENABLED=true
BRANDMATE_AUTH_PUBLIC_WEB_URL=https://brandmate.example.com
BRANDMATE_AUTH_RATE_LIMIT_BACKEND=postgres
```

운영에서는 아래 조합을 허용하지 않는다.

- 짧거나 기본값인 JWT secret
- `Secure=false` Refresh Cookie
- `__Host-` prefix 없는 운영 Refresh Cookie
- 이메일 인증 비활성화
- SMTP 설정 누락
- HTTP public web URL
- memory rate limit backend

## 로컬 실행

API 서버:

```bash
# [Design Intent] API는 apps/api를 working directory로 실행해야 app import 경로가 맞는다.
cd apps/api
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 7660
```

프론트 정적 서버:

```bash
# [Design Intent] apps/web은 빌드 도구 없이 정적 파일 서버로 로컬 확인한다.
cd apps/web
python -m http.server 5501
```

접속 주소:

- Web: `http://127.0.0.1:5501/`
- API docs: `http://127.0.0.1:7660/docs`
- Health: `http://127.0.0.1:7660/health`

PostgreSQL은 인증 기능에 필수다. `docker-compose.api.yml`은 API를 Docker화하려고 만든 파일이 아니라, 로컬/테스트 PostgreSQL을 재현 가능하게 띄우기 위한 보조 파일이다.

## 팀 테스트 계정 공유 정책

실제 로그인 비밀번호는 git에 올라가는 문서, README, issue, PR description에 쓰지 않는다. 테스트 계정이 필요하면 이메일만 문서에 남기고 비밀번호는 팀의 비공개 채널이나 secret manager로 공유한다.

현재 로컬/스테이징 테스트 계정이 필요하면 아래 형식을 사용한다.

```text
# [Design Intent] 계정 식별자만 문서화하고 password는 추적되는 저장소에 남기지 않는다.
email: admin@admin.com
password: 팀 비공개 채널에서 공유
scope: local/staging smoke test only
```

공개 배포 환경에서 공유 admin 계정을 계속 쓰는 것은 금지한다. 필요한 경우 개인별 계정을 만들고, 관리자 권한은 별도 RBAC와 감사 로그가 생긴 뒤 부여한다.

## 테스트

인증 테스트 위치는 `apps/api/tests`다.

```bash
# [Design Intent] 인증 변경은 API contract, service rule, DB migration을 같이 검증한다.
cd apps/api
.venv\Scripts\python.exe -m pytest
```

현재 자동화된 검증 범위:

- 회원가입, 로그인, Refresh, 로그아웃
- Argon2id hash 저장
- Refresh rotation과 reuse detection
- 동시 가입 UNIQUE 제약
- 전체 로그아웃과 특정 session 폐기
- 이메일 인증 전 로그인 거부
- 비밀번호 재설정/변경 후 기존 session 거부
- CORS/Origin/CSRF 방어
- Web Storage에 token 저장하지 않는 정적 회귀 테스트
- PostgreSQL rate limit 원자성
- SMTP timeout 후 outbox retry
- Prometheus metric에 이메일/token 미노출
- Alembic `upgrade -> downgrade -> upgrade`

## 공개 배포 전 남은 항목

아래는 코드로만 끝낼 수 없는 항목이다.

- 실제 SMTP 자격 증명과 발신 도메인으로 인증/재설정 메일 수신 확인
- 실제 HTTPS 브라우저에서 `Secure`, `HttpOnly`, `SameSite`, `__Host-` Cookie 확인
- 실제 브라우저 두 탭에서 Refresh 경쟁이 없는지 E2E 확인
- 운영 metric scraper/dashboard 연결 확인
- 약관 동의가 필요한지 결정하고, 필요하면 확정된 문서 version 기준으로 동의 이력 schema/API 구현

약관 동의는 체크박스 하나 추가한다고 끝나는 기능이 아니다. 법적 문서 version, 필수/선택 여부, 철회 정책이 확정되기 전에는 가짜 동의 데이터를 저장하지 않는다.

## L3 확장 후보

현재 MVP에 바로 넣지 않은 항목이다.

- Redis rate limiter 전환
- HS256에서 비대칭 서명 키와 `kid` 기반 rotation으로 전환
- OpenTelemetry 분산 tracing
- MFA
- 관리자 강제 로그아웃 API와 감사 로그
- 계정 탈취 탐지와 보안 알림
- Outbox worker backpressure와 provider별 circuit breaker
