from typing import Any

try:
    import strawberry
    from strawberry.fastapi import BaseContext, GraphQLRouter
    from fastapi import Request

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

from db_graphql_gateway.auth.interfaces import AuthenticationProvider


class GatewayGraphQLContext(BaseContext):
    def __init__(self, auth_provider: AuthenticationProvider | None = None) -> None:
        super().__init__()
        self.auth_provider = auth_provider

    async def build(self, request: "Request") -> dict[str, Any]:
        context: dict[str, Any] = {"request": request}
        if self.auth_provider and request:
            headers = dict(request.headers)
            auth_context = await self.auth_provider.authenticate(headers)
            context["auth_context"] = auth_context
        return context


def make_graphql_router(
    schema: "strawberry.Schema",
    auth_provider: AuthenticationProvider | None = None,
    path: str = "/graphql",
    max_depth: int | None = 15,
    max_tokens: int | None = 2000,
    disable_introspection: bool = False,
) -> "GraphQLRouter":
    if not _HAS_FASTAPI:
        raise ImportError(
            "FastAPI integration requires the 'fastapi' extra. "
            "Install with: pip install db-graphql-gateway[fastapi]"
        )

    new_extensions = list(schema.extensions)
    if max_depth is not None:
        from strawberry.extensions import QueryDepthLimiter

        new_extensions.append(QueryDepthLimiter(max_depth=max_depth))  # type: ignore[arg-type]
    if max_tokens is not None:
        from strawberry.extensions import MaxTokensLimiter

        new_extensions.append(MaxTokensLimiter(max_token_count=max_tokens))  # type: ignore[arg-type]
    if disable_introspection:
        from strawberry.extensions import DisableIntrospection

        new_extensions.append(DisableIntrospection)

    schema.extensions = tuple(new_extensions)

    async def context_getter(request: Request) -> dict[str, Any]:
        context: dict[str, Any] = {"request": request}
        if auth_provider and request:
            headers = {k.lower(): v for k, v in request.headers.items()}
            auth_context = await auth_provider.authenticate(headers)
            if auth_context.error:
                from fastapi import HTTPException

                raise HTTPException(status_code=401, detail=auth_context.error)
            context["auth_context"] = auth_context
        return context

    return GraphQLRouter(schema=schema, context_getter=context_getter, path=path)
