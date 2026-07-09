from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt import PyJWKClient, PyJWKClientError


@dataclass(frozen=True)
class TokenPrincipal:
    subject: str
    client_id: str
    scopes: frozenset[str]
    auth_time: datetime | None = None


class Auth0TokenVerifier:
    def __init__(self, issuer: str, audience: str, jwks_client=None) -> None:
        self.issuer = issuer.rstrip("/") + "/"
        self.audience = audience
        self.jwks_client = jwks_client or PyJWKClient(f"{self.issuer}.well-known/jwks.json")

    def verify(self, token: str) -> TokenPrincipal:
        try:
            key = self.jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            return self.validate_claims(claims)
        except (jwt.InvalidTokenError, PyJWKClientError) as exc:
            raise PermissionError("invalid access token") from exc

    def validate_claims(self, claims: dict[str, Any]) -> TokenPrincipal:
        if claims.get("iss") != self.issuer:
            raise PermissionError("invalid token issuer")
        audience = claims.get("aud")
        if isinstance(audience, str):
            if audience != self.audience:
                raise PermissionError("invalid token audience")
        elif isinstance(audience, list):
            if self.audience not in audience:
                raise PermissionError("invalid token audience")
        else:
            raise PermissionError("invalid token audience")

        subject = claims.get("sub")
        client_id = claims.get("azp") or claims.get("client_id")
        if (
            not isinstance(subject, str)
            or not isinstance(client_id, str)
            or not subject.strip()
            or not client_id.strip()
        ):
            raise PermissionError("token identity claims are incomplete")

        scope_claim = claims.get("scope", "")
        if isinstance(scope_claim, str):
            scopes = frozenset(scope_claim.split())
        else:
            scopes = frozenset()

        auth_time_claim = claims.get("auth_time")
        auth_time = (
            datetime.fromtimestamp(auth_time_claim, tz=UTC)
            if isinstance(auth_time_claim, int | float)
            and not isinstance(auth_time_claim, bool)
            else None
        )

        return TokenPrincipal(
            subject=subject,
            client_id=client_id,
            scopes=scopes,
            auth_time=auth_time,
        )
