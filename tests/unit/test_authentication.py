import datetime
import jwt
import pytest

from db_graphql_gateway.auth.jwt_provider import JWTAuthenticationProvider


SECRET = "super-secret-key-12345"


@pytest.mark.asyncio
async def test_jwt_valid_token() -> None:
    provider = JWTAuthenticationProvider(secret_or_key=SECRET)
    payload = {
        "sub": "user_123",
        "roles": ["admin", "editor"],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is True
    assert auth_ctx.user_id == "user_123"
    assert auth_ctx.roles == ["admin", "editor"]
    assert auth_ctx.error is None


@pytest.mark.asyncio
async def test_jwt_expired_token() -> None:
    provider = JWTAuthenticationProvider(secret_or_key=SECRET)
    payload = {
        "sub": "user_123",
        "exp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error == "Token has expired"


@pytest.mark.asyncio
async def test_jwt_invalid_signature() -> None:
    provider = JWTAuthenticationProvider(secret_or_key=SECRET)
    payload = {
        "sub": "user_123",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, "wrong-secret-key", algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error is not None
    assert "Invalid token" in auth_ctx.error


@pytest.mark.asyncio
async def test_jwt_wrong_issuer() -> None:
    provider = JWTAuthenticationProvider(secret_or_key=SECRET, issuer="https://auth.myapi.com")
    payload = {
        "sub": "user_123",
        "iss": "https://wrong-issuer.com",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error == "Invalid token issuer"


@pytest.mark.asyncio
async def test_jwt_wrong_audience() -> None:
    provider = JWTAuthenticationProvider(secret_or_key=SECRET, audience="my-api-aud")
    payload = {
        "sub": "user_123",
        "aud": "wrong-api-aud",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error == "Invalid token audience"


@pytest.mark.asyncio
async def test_jwt_bad_algorithm() -> None:
    # Expecting HS256, but token encoded with none/unallowed algorithm
    provider = JWTAuthenticationProvider(secret_or_key=SECRET, algorithms=["RS256"])
    payload = {
        "sub": "user_123",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error == "Invalid token algorithm"


@pytest.mark.asyncio
async def test_jwt_alg_none_attack() -> None:
    """Verify that tokens with algorithm='none' are always rejected."""
    provider = JWTAuthenticationProvider(secret_or_key=SECRET, algorithms=["HS256"])
    payload = {
        "sub": "attacker",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    # Manually craft a token header with alg: none
    # PyJWT should reject this — we verify the rejection here
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).rstrip(
        b"="
    )
    body = base64.urlsafe_b64encode(json.dumps(payload, default=str).encode()).rstrip(b"=")
    forged_token = f"{header.decode()}.{body.decode()}."

    headers = {"Authorization": f"Bearer {forged_token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is False
    assert auth_ctx.error is not None


@pytest.mark.asyncio
async def test_jwt_rs256_valid_token() -> None:
    """Verify that RS256 (asymmetric) tokens are correctly validated."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    # Generate RSA keypair
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    provider = JWTAuthenticationProvider(secret_or_key=public_pem.decode(), algorithms=["RS256"])
    payload = {
        "sub": "user_rs256",
        "roles": ["viewer"],
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    token = jwt.encode(payload, private_pem, algorithm="RS256")

    headers = {"Authorization": f"Bearer {token}"}
    auth_ctx = await provider.authenticate(headers)

    assert auth_ctx.is_authenticated is True
    assert auth_ctx.user_id == "user_rs256"
    assert auth_ctx.roles == ["viewer"]


@pytest.mark.asyncio
async def test_jwt_algorithm_confusion_attack() -> None:
    """Verify that RS256 public key cannot be used as HS256 secret (algorithm confusion)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Provider expects RS256
    provider = JWTAuthenticationProvider(secret_or_key=public_pem.decode(), algorithms=["RS256"])

    payload = {
        "sub": "attacker",
        "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    }
    # Attacker tries to sign with HS256 using the public key as shared secret
    try:
        confused_token = jwt.encode(payload, public_pem, algorithm="HS256")
    except Exception:
        # PyJWT may reject this at encode time — that's fine, attack blocked
        return

    headers = {"Authorization": f"Bearer {confused_token}"}
    auth_ctx = await provider.authenticate(headers)

    # Must NOT authenticate
    assert auth_ctx.is_authenticated is False
