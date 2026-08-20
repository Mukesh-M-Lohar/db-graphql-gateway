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
) -> "GraphQLRouter":
    if not _HAS_FASTAPI:
        raise ImportError(
            "FastAPI integration requires the 'fastapi' extra. "
            "Install with: pip install db-graphql-gateway[fastapi]"
        )

    async def context_getter(request: Request) -> dict[str, Any]:
        context: dict[str, Any] = {"request": request}
        if auth_provider and request:
            headers = {k.lower(): v for k, v in request.headers.items()}
            auth_context = await auth_provider.authenticate(headers)
            context["auth_context"] = auth_context
        return context

    return GraphQLRouter(schema=schema, context_getter=context_getter, path=path)
