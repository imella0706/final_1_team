from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.params import Depends as DependsParam
from fastapi.routing import APIRoute, APIRouter


def register_router(
    app: FastAPI,
    router: APIRouter,
    *,
    prefix: str = "",
    dependencies: Sequence[DependsParam] = (),
) -> None:
    # [Design Intent] FastAPI 0.139 can keep included routers lazy in this project,
    # leaving endpoints unreachable. Register concrete APIRoute objects so each
    # service entrypoint exposes the same runtime API surface.
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        app.add_api_route(
            f"{prefix}{route.path}",
            route.endpoint,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=route.tags,
            dependencies=[*route.dependencies, *dependencies],
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=route.responses,
            deprecated=route.deprecated,
            methods=route.methods,
            operation_id=route.operation_id,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            response_class=route.response_class,
            name=route.name,
            openapi_extra=route.openapi_extra,
        )
