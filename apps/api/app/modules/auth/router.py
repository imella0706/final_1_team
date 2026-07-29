from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response, status

from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.dependencies import (
    AuthContext,
    get_auth_service,
    get_config,
    get_current_auth,
    get_current_user,
)
from app.modules.auth.models import User
from app.modules.auth.rate_limit import AuthRateLimiterPort
from app.modules.auth.schemas import (
    AcceptedResponse,
    ActionTokenRequest,
    LoginRequest,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionListResponse,
    SignupRequest,
    SignupResponse,
    TokenResponse,
    UserPublic,
)
from app.modules.auth.service import AuthService, IssuedTokens, normalize_email, to_public_user

router = APIRouter(prefix="/auth", tags=["auth"])


def request_identity(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def validate_browser_origin(request: Request, config: Settings) -> None:
    origin = request.headers.get("origin")
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site == "cross-site" or (
        origin is not None and origin.rstrip("/") not in config.allowed_web_origins
    ):
        raise ApiError(403, "AUTH_ORIGIN_FORBIDDEN", "허용되지 않은 요청 출처입니다.")


async def enforce_rate_limit(
    request: Request,
    *,
    scope: str,
    identity: str,
    limit: int,
    window: int,
) -> None:
    limiter: AuthRateLimiterPort = request.app.state.auth_rate_limiter
    await limiter.check(scope=scope, identity=identity, limit=limit, window=window)


def set_refresh_cookie(
    response: Response,
    token: str,
    config: Settings,
) -> None:
    response.set_cookie(
        key=config.auth_refresh_cookie_name,
        value=token,
        max_age=config.auth_refresh_token_days * 24 * 60 * 60,
        httponly=True,
        secure=config.auth_refresh_cookie_secure,
        samesite=config.auth_refresh_cookie_samesite,
        path="/",
    )


def prevent_token_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def clear_refresh_cookie(response: Response, config: Settings) -> None:
    response.delete_cookie(
        key=config.auth_refresh_cookie_name,
        httponly=True,
        secure=config.auth_refresh_cookie_secure,
        samesite=config.auth_refresh_cookie_samesite,
        path="/",
    )


def token_response(issued: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=issued.access_token,
        expires_in=issued.expires_in,
        user=to_public_user(issued.user),
    )


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> SignupResponse:
    validate_browser_origin(request, config)
    await enforce_rate_limit(
        request,
        scope="signup",
        identity=request_identity(request),
        limit=config.auth_signup_limit_per_5_minutes,
        window=300,
    )
    user = await service.signup(payload)
    return SignupResponse(user=to_public_user(user))


@router.post("/verify-email", response_model=SignupResponse)
async def verify_email(
    payload: ActionTokenRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> SignupResponse:
    validate_browser_origin(request, config)
    user = await service.verify_email(payload.token.get_secret_value())
    return SignupResponse(user=to_public_user(user))


@router.post(
    "/verify-email/resend",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resend_verification(
    payload: PasswordResetRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> AcceptedResponse:
    validate_browser_origin(request, config)
    await enforce_rate_limit(
        request,
        scope="verify_email_resend",
        identity=normalize_email(str(payload.email)),
        limit=3,
        window=900,
    )
    await service.resend_verification(str(payload.email))
    return AcceptedResponse(message="확인 가능한 계정이면 인증 메일을 전송합니다.")


@router.post(
    "/password-reset/request",
    response_model=AcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> AcceptedResponse:
    validate_browser_origin(request, config)
    await enforce_rate_limit(
        request,
        scope="password_reset",
        identity=normalize_email(str(payload.email)),
        limit=3,
        window=900,
    )
    await service.request_password_reset(str(payload.email))
    # [Design Intent] Existing and missing accounts receive the same contract,
    # blocking email-address enumeration through the recovery endpoint.
    return AcceptedResponse(message="확인 가능한 계정이면 재설정 메일을 전송합니다.")


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> Response:
    validate_browser_origin(request, config)
    await service.reset_password(
        payload.token.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, config)
    return response


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> TokenResponse:
    validate_browser_origin(request, config)
    await enforce_rate_limit(
        request,
        scope="login_ip",
        identity=request_identity(request),
        limit=config.auth_login_ip_limit_per_5_minutes,
        window=300,
    )
    await enforce_rate_limit(
        request,
        scope="login_account",
        identity=normalize_email(str(payload.email)),
        limit=config.auth_login_limit_per_5_minutes,
        window=300,
    )
    issued = await service.login(
        payload,
        existing_refresh_token=request.cookies.get(config.auth_refresh_cookie_name),
    )
    set_refresh_cookie(response, issued.refresh_token, config)
    prevent_token_caching(response)
    return token_response(issued)


@router.post("/local-login", response_model=TokenResponse)
async def local_login(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> TokenResponse:
    validate_browser_origin(request, config)
    client_host = request.client.host if request.client else ""
    is_local_client = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if (
        not config.auth_local_login_bypass
        or config.environment.lower() in {"production", "prod"}
        or not is_local_client
    ):
        raise ApiError(404, "AUTH_LOCAL_LOGIN_DISABLED", "로컬 자동 로그인을 사용할 수 없습니다.")

    issued = await service.login_for_local_development(
        email=config.auth_local_login_email,
        display_name=config.auth_local_login_display_name,
        device_name="로컬 테스트 페이지",
    )
    set_refresh_cookie(response, issued.refresh_token, config)
    prevent_token_caching(response)
    return token_response(issued)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
    refresh_token: Annotated[str | None, Cookie(alias="brandmate_refresh")] = None,
) -> TokenResponse:
    validate_browser_origin(request, config)
    await enforce_rate_limit(
        request,
        scope="refresh",
        identity=request_identity(request),
        limit=config.auth_refresh_limit_per_minute,
        window=60,
    )
    # A configurable production cookie name is read directly because Cookie(alias)
    # is fixed at route construction time.
    raw_token = request.cookies.get(config.auth_refresh_cookie_name) or refresh_token
    issued = await service.refresh(raw_token)
    set_refresh_cookie(response, issued.refresh_token, config)
    prevent_token_caching(response)
    return token_response(issued)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> Response:
    validate_browser_origin(request, config)
    await service.logout(request.cookies.get(config.auth_refresh_cookie_name))
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, config)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout_all(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> Response:
    validate_browser_origin(request, config)
    await service.logout_all(user)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, config)
    return response


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> Response:
    validate_browser_origin(request, config)
    await service.change_password(
        user,
        current_password=payload.current_password.get_secret_value(),
        new_password=payload.new_password.get_secret_value(),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, config)
    return response


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(
    context: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionListResponse:
    sessions = await service.list_sessions(context.user, context.session.id)
    return SessionListResponse(sessions=sessions)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def revoke_session(
    session_id: UUID,
    request: Request,
    context: Annotated[AuthContext, Depends(get_current_auth)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    config: Annotated[Settings, Depends(get_config)],
) -> Response:
    validate_browser_origin(request, config)
    await service.revoke_session(context.user, session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if session_id == context.session.id:
        clear_refresh_cookie(response, config)
    return response


@router.get("/me", response_model=UserPublic)
async def me(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    response.headers["Cache-Control"] = "private, no-store"
    return to_public_user(user)
