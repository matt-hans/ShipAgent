"""Browser session exchange for API-key authenticated deployments."""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from src.api.browser_session import (
    BROWSER_SESSION_COOKIE,
    BROWSER_SESSION_TTL_SECONDS,
    derive_browser_csrf_token,
    issue_browser_session,
    verify_browser_session,
)
from src.api.middleware.auth import get_expected_api_key

router = APIRouter(prefix="/auth/session", tags=["authentication"])


class BrowserSessionStatus(BaseModel):
    """Minimal browser authentication state exposed to the shell."""

    required: bool
    authenticated: bool
    csrf_token: str | None


def _session_status(request: Request) -> BrowserSessionStatus:
    expected_key = get_expected_api_key()
    required = bool(expected_key)
    session_token = request.cookies.get(BROWSER_SESSION_COOKIE)
    authenticated = not required or verify_browser_session(
        session_token,
        expected_key,
    )
    return BrowserSessionStatus(
        required=required,
        authenticated=authenticated,
        csrf_token=(
            derive_browser_csrf_token(session_token, expected_key)
            if required and authenticated and session_token is not None
            else None
        ),
    )


@router.get("")
def get_browser_session_status(request: Request) -> BrowserSessionStatus:
    """Report whether the browser must establish an API session."""
    return _session_status(request)


@router.post("")
def create_browser_session(
    request: Request,
    response: Response,
) -> BrowserSessionStatus:
    """Exchange middleware-authenticated API credentials for an HttpOnly cookie."""
    expected_key = get_expected_api_key()
    csrf_token = None
    if expected_key:
        session_token = issue_browser_session(expected_key)
        response.set_cookie(
            BROWSER_SESSION_COOKIE,
            session_token,
            max_age=BROWSER_SESSION_TTL_SECONDS,
            path="/api",
            secure=request.url.scheme == "https",
            httponly=True,
            samesite="strict",
        )
        csrf_token = derive_browser_csrf_token(session_token, expected_key)
    return BrowserSessionStatus(
        required=bool(expected_key),
        authenticated=True,
        csrf_token=csrf_token,
    )


@router.delete("")
def delete_browser_session(
    request: Request,
    response: Response,
) -> BrowserSessionStatus:
    """Expire the browser session cookie without requiring authentication."""
    response.delete_cookie(
        BROWSER_SESSION_COOKIE,
        path="/api",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    required = bool(get_expected_api_key())
    return BrowserSessionStatus(
        required=required,
        authenticated=not required,
        csrf_token=None,
    )
