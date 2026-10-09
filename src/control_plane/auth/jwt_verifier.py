"""Verified request identity; no token value can choose its own link claim."""

import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient, PyJWKClientError

LINK_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


def validate_provider_link_claim(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        valid = (
            type(value) is str
            and 1 <= len(value) <= 512
            and value.isascii()
            and not any(ord(c) <= 32 or ord(c) == 127 for c in value)
            and "\\" not in value
            and "?" not in value
            and "#" not in value
            and parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and bool(parsed.path.strip("/"))
            and not parsed.query
            and not parsed.fragment
        )
        _ = parsed.port
    except (ValueError, TypeError, AttributeError):
        valid = False
    if not valid:
        raise ValueError("provider link claim must be a bounded HTTPS namespace URI")
    return value


def timestamp(value: object) -> float:
    """Require a finite numeric UTC timestamp representable by this runtime."""
    try:
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError
        result = float(value)
        datetime.fromtimestamp(result, tz=UTC)
        return result
    except (ValueError, TypeError, OverflowError, OSError):
        raise PermissionError("invalid token timestamp") from None


@dataclass(frozen=True)
class TokenPrincipal:
    subject: str
    client_id: str
    scopes: frozenset[str]
    auth_time: datetime | None = None
    issuer: str | None = None
    issued_at: float | None = None
    expires_at: float | None = None
    issuer_link_id: str | None = None


class Auth0TokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        jwks_client=None,
        *,
        provider_link_claim: str | None = None,
    ) -> None:
        self.issuer = issuer.rstrip("/") + "/"
        self.audience = audience
        self.provider_link_claim = validate_provider_link_claim(provider_link_claim)
        self.jwks_client = jwks_client or PyJWKClient(
            f"{self.issuer}.well-known/jwks.json"
        )

    def verify(self, token: str) -> TokenPrincipal:
        try:
            key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                # Validate exact finite fractional times below. PyJWT's integer
                # coercion accepts booleans/strings and truncates fractional expiry.
                options={
                    "require": ["exp", "iat", "iss", "aud", "sub"],
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
            return self.validate_claims(claims)
        except (
            jwt.InvalidTokenError,
            PyJWKClientError,
            ValueError,
            TypeError,
            OverflowError,
        ):
            raise PermissionError("invalid access token") from None

    def validate_claims(self, claims: dict[str, Any]) -> TokenPrincipal:
        if claims.get("iss") != self.issuer:
            raise PermissionError("invalid token issuer")
        audience = claims.get("aud")
        if not (
            audience == self.audience
            or isinstance(audience, list)
            and self.audience in audience
        ):
            raise PermissionError("invalid token audience")
        issued_at = timestamp(claims.get("iat"))
        expires_at = timestamp(claims.get("exp"))
        now = time.time()
        if issued_at > now or expires_at <= now or issued_at >= expires_at:
            raise PermissionError("invalid token lifetime")
        subject = claims.get("sub")
        client_id = claims.get("azp") or claims.get("client_id")
        if any(
            type(value) is not str or not value.strip() or len(value) > 255
            for value in (subject, client_id)
        ):
            raise PermissionError("token identity claims are incomplete")
        link_id = None
        if self.provider_link_claim is not None:
            link_id = claims.get(self.provider_link_claim)
            if type(link_id) is not str or LINK_ID_PATTERN.fullmatch(link_id) is None:
                raise PermissionError("invalid provider link claim")
        scope_claim = claims.get("scope", "")
        scopes = (
            frozenset(scope_claim.split())
            if isinstance(scope_claim, str)
            else frozenset()
        )
        auth_time_claim = claims.get("auth_time")
        auth_time = (
            datetime.fromtimestamp(timestamp(auth_time_claim), tz=UTC)
            if type(auth_time_claim) in (int, float)
            else None
        )
        return TokenPrincipal(
            subject=subject,
            client_id=client_id,
            scopes=scopes,
            auth_time=auth_time,
            issuer=self.issuer,
            issued_at=issued_at,
            expires_at=expires_at,
            issuer_link_id=link_id,
        )
