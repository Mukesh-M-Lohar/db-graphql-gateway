from typing import Any
import jwt

from db_graphql_gateway.auth.interfaces import AuthContext, AuthenticationProvider


class JWTAuthenticationProvider(AuthenticationProvider):
    def __init__(
        self,
        secret_or_key: str,
        algorithms: list[str] | None = None,
        issuer: str | None = None,
        audience: str | None = None,
        user_id_claim: str = "sub",
        roles_claim: str = "roles",
    ) -> None:
        self.secret_or_key = secret_or_key
        self.algorithms = algorithms or ["HS256"]
        self.issuer = issuer
        self.audience = audience
        self.user_id_claim = user_id_claim
        self.roles_claim = roles_claim

    async def authenticate(self, headers: dict[str, str]) -> AuthContext:
        auth_header = None
        for k, v in headers.items():
            if k.lower() == "authorization":
                auth_header = v
                break

        if not auth_header:
            return AuthContext(is_authenticated=False)

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return AuthContext(is_authenticated=False, error="Invalid authorization header format")

        token = parts[1]

        try:
            options = {
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": self.issuer is not None,
                "verify_aud": self.audience is not None,
            }

            payload: dict[str, Any] = jwt.decode(
                token,
                self.secret_or_key,
                algorithms=self.algorithms,
                issuer=self.issuer,
                audience=self.audience,
                options=options,  # type: ignore[arg-type]
            )

            user_id = payload.get(self.user_id_claim)
            roles = payload.get(self.roles_claim, [])
            if isinstance(roles, str):
                roles = [roles]

            return AuthContext(
                user_id=user_id if user_id is not None else None,
                roles=list(roles),
                claims=payload,
                is_authenticated=True,
            )

        except jwt.ExpiredSignatureError:
            return AuthContext(is_authenticated=False, error="Token has expired")
        except jwt.InvalidIssuerError:
            return AuthContext(is_authenticated=False, error="Invalid token issuer")
        except jwt.InvalidAudienceError:
            return AuthContext(is_authenticated=False, error="Invalid token audience")
        except jwt.InvalidAlgorithmError:
            return AuthContext(is_authenticated=False, error="Invalid token algorithm")
        except jwt.PyJWTError as e:
            return AuthContext(is_authenticated=False, error=f"Invalid token: {str(e)}")
