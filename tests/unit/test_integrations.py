from typing import Any, cast
import pytest
import strawberry
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db_graphql_gateway.auth.interfaces import AuthContext, AuthenticationProvider
from db_graphql_gateway.integrations.fastapi_integration import make_graphql_router


class MockAuthProvider(AuthenticationProvider):
    async def authenticate(self, headers: dict[str, str]) -> AuthContext:
        token = headers.get("authorization", "")
        if "valid" in token:
            return AuthContext(user_id="user_fastapi", is_authenticated=True)
        return AuthContext(is_authenticated=False)


@pytest.mark.asyncio
async def test_fastapi_graphql_router() -> None:
    pass

    @strawberry.type
    class Query:
        @strawberry.field
        def me(self, info: strawberry.types.Info) -> str:
            auth_ctx: AuthContext | None = info.context.get("auth_context")
            if auth_ctx and auth_ctx.is_authenticated:
                return f"Hello {auth_ctx.user_id}"
            return "Hello Anonymous"

    schema = strawberry.Schema(query=Query)
    router = make_graphql_router(schema, auth_provider=MockAuthProvider(), path="/graphql")

    app = FastAPI()
    app.include_router(router)

    client = TestClient(app)

    # 1. Anonymous request
    res_anon = client.post("/graphql", json={"query": "{ me }"})
    assert res_anon.status_code == 200
    assert cast(dict[str, Any], res_anon.json())["data"]["me"] == "Hello Anonymous"

    # 2. Authenticated request
    res_auth = client.post(
        "/graphql",
        json={"query": "{ me }"},
        headers={"authorization": "Bearer valid_token"},
    )
    assert res_auth.status_code == 200
    assert cast(dict[str, Any], res_auth.json())["data"]["me"] == "Hello user_fastapi"
