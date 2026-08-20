from db_graphql_gateway.auth.interfaces import AuthContext, AuthenticationProvider


async def get_auth_context_from_headers(
    headers: dict[str, str],
    auth_provider: AuthenticationProvider | None = None,
) -> AuthContext:
    if auth_provider is None:
        return AuthContext(is_authenticated=False)
    return await auth_provider.authenticate(headers)
