# Copyright (c) 2025-2026 Sunet.
# Contributor: Kristofer Hallin
#
# This file is part of Sunet Scribe.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Signing in as a user with the OAuth device flow, and remembering it.

``login()`` shows a short code and a URL; the user opens it in a browser and
signs in as usual (SSO, MFA and all). No client id, secret or password is
needed. Only the refresh token is saved, so the API token can be renewed
without signing in again.
"""

import json
import os
import tempfile
import time
import warnings
from collections.abc import Callable
from pathlib import Path

import requests

from .auth import (
    Token,
    http_error_message,
    post_token,
    require_https,
    token_from_body,
)
from .constants import DEFAULT_OIDC_CLIENT_ID, DEFAULT_OIDC_ISSUER
from .errors import AuthError

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
LOGIN_HINT = "Run `python -m scribe login` to sign in."


def oidc_settings() -> tuple[str, str]:
    """(issuer, client id), from the environment or the defaults."""
    return (
        os.environ.get("SCRIBE_OIDC_ISSUER", DEFAULT_OIDC_ISSUER).rstrip("/"),
        os.environ.get("SCRIBE_OIDC_CLIENT_ID", DEFAULT_OIDC_CLIENT_ID),
    )


def _endpoint(issuer: str, name: str) -> str:
    return f"{issuer}/protocol/openid-connect/{name}"


def token_path() -> Path:
    """Where the login is saved: ``$SCRIBE_TOKEN_FILE``, else
    ``~/.config/scribe/token.json`` (honouring ``XDG_CONFIG_HOME``)."""
    if os.environ.get("SCRIBE_TOKEN_FILE"):
        return Path(os.environ["SCRIBE_TOKEN_FILE"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "scribe" / "token.json"


def save_login(issuer: str, client_id: str, refresh_token: str) -> None:
    """Save the refresh token, readable by this user only."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write a private temp file, then move it into place, so the token is
    # never readable by others, even briefly.
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".token-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(
                {
                    "issuer": issuer,
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                },
                f,
            )
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def load_login() -> dict | None:
    """The saved login, or None if there is none (or it is unreadable)."""
    path = token_path()
    try:
        if os.name != "nt" and path.stat().st_mode & 0o077:
            warnings.warn(
                f"{path} can be read by other users; run: chmod 600 {path}",
                stacklevel=2,
            )
        saved = json.loads(path.read_text())
        if all(isinstance(saved.get(k), str) for k in ("issuer", "client_id", "refresh_token")):
            return saved
    except (OSError, ValueError, AttributeError):
        pass
    return None


def logout() -> bool:
    """Forget the saved login. Returns False if there was none."""
    try:
        token_path().unlink()
        return True
    except FileNotFoundError:
        return False


def login(
    issuer: str | None = None,
    client_id: str | None = None,
    prompt: Callable[[str, str], None] | None = None,
    timeout: int = 10,
) -> None:
    """Sign in with the device flow and save the login.

    ``prompt(url, code)`` shows the user where to go; the default prints it.
    Waits until the user has signed in, said no, or the code has expired.
    """
    default_issuer, default_client = oidc_settings()
    issuer = (issuer or default_issuer).rstrip("/")
    client_id = client_id or default_client
    require_https(issuer)

    try:
        response = requests.post(
            _endpoint(issuer, "auth/device"),
            data={"client_id": client_id, "scope": "openid"},
            timeout=timeout,
        )
        if not response.ok:
            raise AuthError(
                http_error_message(response, _endpoint(issuer, "auth/device")).replace(
                    "get token from", "start login at"
                )
            )
        device = response.json()
        device_code = device["device_code"]
        url = device.get("verification_uri_complete") or device["verification_uri"]
        code = device["user_code"]
        interval = float(device.get("interval", 5))
        deadline = time.monotonic() + float(device.get("expires_in", 600))
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        raise AuthError(f"Could not start login: {type(e).__name__}") from e

    if prompt:
        prompt(url, code)
    else:
        print(f"Open {url}\nand check that the code is: {code}", flush=True)

    token_endpoint = _endpoint(issuer, "token")
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            response = requests.post(
                token_endpoint,
                data={
                    "grant_type": DEVICE_GRANT,
                    "device_code": device_code,
                    "client_id": client_id,
                },
                timeout=timeout,
            )
            body = response.json()
        except (requests.RequestException, ValueError) as e:
            raise AuthError(f"Login failed: {type(e).__name__}") from e

        if response.ok:
            try:
                save_login(issuer, client_id, body["refresh_token"])
            except KeyError as e:
                raise AuthError(
                    "The provider sent no refresh token; is the client allowed "
                    "to get one?"
                ) from e
            return
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise AuthError("Login was denied.")
        if error == "expired_token":
            break
        raise AuthError(http_error_message(response, token_endpoint))

    raise AuthError("Login timed out; the code expired. Try again.")


def saved_login_token_source() -> Callable[[], Token]:
    """A token source that renews the access token from the saved login.

    Raises ``AuthError`` right away if nobody has signed in.
    """
    if load_login() is None:
        raise AuthError(f"Not signed in. {LOGIN_HINT}")

    def source() -> Token:
        saved = load_login()
        if saved is None:
            raise AuthError(f"Not signed in. {LOGIN_HINT}")
        try:
            body = post_token(
                _endpoint(saved["issuer"], "token"),
                {
                    "grant_type": "refresh_token",
                    "client_id": saved["client_id"],
                    "refresh_token": saved["refresh_token"],
                },
                10,
            )
            token = token_from_body(body)
        except AuthError as e:
            if "invalid_grant" in str(e):
                raise AuthError(f"Your login has expired. {LOGIN_HINT}") from e
            raise
        except (KeyError, TypeError, ValueError) as e:
            raise AuthError(f"Could not get token: {type(e).__name__}") from e
        # Keycloak may hand out a new refresh token; keep the newest.
        new_refresh = body.get("refresh_token")
        if new_refresh and new_refresh != saved["refresh_token"]:
            save_login(saved["issuer"], saved["client_id"], new_refresh)
        return token

    return source
