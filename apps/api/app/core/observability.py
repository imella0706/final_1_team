import json
import logging
import time
from collections import defaultdict
from uuid import uuid4

from fastapi import FastAPI, Request

logger = logging.getLogger("brandmate.request")

AUTH_LATENCY_BUCKETS_MS = (50, 100, 250, 500, 1000, 2500, 5000)


class AuthMetrics:
    def __init__(self) -> None:
        self.request_counts: dict[tuple[str, str, int], int] = defaultdict(int)
        self.error_counts: dict[tuple[str, str], int] = defaultdict(int)
        self.latency_buckets: dict[tuple[str, int], int] = defaultdict(int)
        self.latency_sum_ms: dict[str, float] = defaultdict(float)
        self.latency_count: dict[str, int] = defaultdict(int)

    def observe(
        self,
        *,
        operation: str,
        result: str,
        status_code: int,
        latency_ms: float,
        failure_code: str | None,
    ) -> None:
        # [Design Intent] Labels are route templates and bounded error codes, never
        # user IDs, emails, tokens, or raw session paths.
        self.request_counts[(operation, result, status_code)] += 1
        if failure_code:
            self.error_counts[(operation, failure_code)] += 1
        self.latency_sum_ms[operation] += latency_ms
        self.latency_count[operation] += 1
        for bucket in AUTH_LATENCY_BUCKETS_MS:
            if latency_ms <= bucket:
                self.latency_buckets[(operation, bucket)] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP brandmate_auth_requests_total Authentication requests.",
            "# TYPE brandmate_auth_requests_total counter",
        ]
        for (operation, result, status_code), count in sorted(self.request_counts.items()):
            lines.append(
                "brandmate_auth_requests_total"
                f'{{operation="{operation}",result="{result}",status="{status_code}"}} {count}'
            )
        lines.extend(
            [
                "# HELP brandmate_auth_errors_total Authentication errors by stable code.",
                "# TYPE brandmate_auth_errors_total counter",
            ]
        )
        for (operation, code), count in sorted(self.error_counts.items()):
            lines.append(
                f'brandmate_auth_errors_total{{operation="{operation}",code="{code}"}} {count}'
            )
        lines.extend(
            [
                "# HELP brandmate_auth_request_latency_ms Authentication request latency.",
                "# TYPE brandmate_auth_request_latency_ms histogram",
            ]
        )
        for operation, count in sorted(self.latency_count.items()):
            for bucket in AUTH_LATENCY_BUCKETS_MS:
                bucket_count = self.latency_buckets[(operation, bucket)]
                lines.append(
                    "brandmate_auth_request_latency_ms_bucket"
                    f'{{operation="{operation}",le="{bucket}"}} {bucket_count}'
                )
            lines.append(
                "brandmate_auth_request_latency_ms_bucket"
                f'{{operation="{operation}",le="+Inf"}} {count}'
            )
            lines.append(
                "brandmate_auth_request_latency_ms_sum"
                f'{{operation="{operation}"}} {self.latency_sum_ms[operation]:.3f}'
            )
            lines.append(
                f'brandmate_auth_request_latency_ms_count{{operation="{operation}"}} {count}'
            )
        return "\n".join(lines) + "\n"


def register_request_logging(app: FastAPI) -> None:
    app.state.auth_metrics = AuthMetrics()

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        # [Design Intent] Log only request metadata. Bodies, Authorization headers,
        # cookies, tokens, and full email addresses must never enter service logs.
        request_id = str(uuid4())
        request.state.request_id = request_id
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        "event": "api_request_failed",
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                    }
                )
            )
            raise

        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        is_auth_request = "/auth/" in route_path
        failure_code = getattr(request.state, "error_code", None)
        if is_auth_request:
            operation = f"{request.method} {route_path}"
            result = "success" if response.status_code < 400 else "failure"
            app.state.auth_metrics.observe(
                operation=operation,
                result=result,
                status_code=response.status_code,
                latency_ms=latency_ms,
                failure_code=failure_code,
            )
            logger.info(
                json.dumps(
                    {
                        "event": "auth_request",
                        "request_id": request_id,
                        "operation": operation,
                        "result": result,
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                        "failure_code": failure_code,
                    }
                )
            )
        logger.info(
            json.dumps(
                {
                    "event": "api_request",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                }
            )
        )
        return response
