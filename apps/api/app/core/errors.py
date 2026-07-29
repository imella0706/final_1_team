import logging
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("brandmate.api")


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] = field(default_factory=dict)
    stage: str | None = None
    retryable: bool | None = None


def register_exception_handlers(app: FastAPI) -> None:
    # [Design Intent] Stable machine-readable error codes let the frontend render
    # states without parsing prose, while validation responses omit raw passwords.
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        request.state.error_code = exc.code
        error_payload: dict[str, object] = {
            "code": exc.code,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", None),
        }
        if exc.stage is not None:
            error_payload["stage"] = exc.stage
        if exc.retryable is not None:
            error_payload["retryable"] = exc.retryable
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={"error": error_payload},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        request.state.error_code = "REQUEST_VALIDATION_FAILED"
        fields = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "reason": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "REQUEST_VALIDATION_FAILED",
                    "message": "요청 값을 확인해 주세요.",
                    "request_id": getattr(request.state, "request_id", None),
                    "fields": fields,
                }
            },
        )
