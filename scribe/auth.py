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

"""Getting a bearer token from the OIDC provider."""

import base64
import json
import time
from dataclasses import dataclass

import requests
from urllib.parse import urlsplit

from .errors import AuthError


@dataclass(frozen=True)
class Token:
    """An access token and when it stops being good.

    ``expires_at`` is on the ``time.monotonic()`` clock, or None when the
    provider did not say.
    """

    access_token: str
    expires_at: float | None = None

    def expired(self, leeway: float = 0.0) -> bool:
        """True if it has expired, or will within ``leeway`` seconds."""
        return self.expires_at is not None and time.monotonic() >= (
            self.expires_at - leeway
        )

    @classmethod
    def from_jwt(cls, jwt: str) -> "Token":
        """Wrap a JWT (e.g. one copied from the web interface).

        The expiry is read from the ``exp`` claim. The signature is *not*
        checked: that is the API's job, this only knows when to stop using
        it. A string that is not a JWT, or has no ``exp``, gets no expiry.
        """
        return cls(jwt, _jwt_expiry(jwt))


def _jwt_expiry(jwt: str) -> float | None:
    """``exp`` of a JWT as a ``time.monotonic()`` value, or None."""
    try:
        payload = jwt.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        exp = float(claims["exp"])
    except (IndexError, KeyError, ValueError, TypeError, AttributeError):
        return None
    return time.monotonic() + (exp - time.time())


def require_https(url: str) -> str:
    """Return ``url`` if it is https (or localhost, for testing); else raise.

    Passwords, secrets and tokens must not cross the network in plain text.
    """
    parts = urlsplit(url)
    if parts.scheme == "https" or (
        parts.scheme == "http" and parts.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        return url
    raise AuthError(f"Refusing to send credentials over a non-https URL: {url}")


def token_from_body(body: dict) -> Token:
    """A ``Token`` from a token endpoint's JSON answer."""
    expires_in = body.get("expires_in")
    return Token(
        access_token=body["access_token"],
        expires_at=(
            time.monotonic() + float(expires_in) if expires_in is not None else None
        ),
    )


def http_error_message(response: requests.Response, token_endpoint: str) -> str:
    """Status plus the provider's OAuth ``error`` and ``error_description``
    (e.g. "Invalid client or Invalid client credentials"). Not the whole body,
    which can echo the request."""
    message = f"Could not get token from {token_endpoint}: HTTP {response.status_code}"
    try:
        body = response.json()
        code, description = body.get("error"), body.get("error_description")
    except (ValueError, AttributeError):
        code = description = None
    if code:
        message += f" {code}"
    if description:
        message += f": {str(description)[:200]}"
    return message


def post_token(token_endpoint: str, data: dict[str, str], timeout: int) -> dict:
    """POST a grant to the token endpoint and return the JSON answer."""
    require_https(token_endpoint)
    try:
        response = requests.post(token_endpoint, data=data, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as e:
        raise AuthError(http_error_message(e.response, token_endpoint)) from e
    except (requests.RequestException, ValueError) as e:
        # Not the response: its body can echo the request.
        raise AuthError(f"Could not get token: {type(e).__name__}") from e


def _request_token(token_endpoint: str, data: dict[str, str], timeout: int) -> Token:
    """POST a grant to the token endpoint and return the token."""
    try:
        return token_from_body(post_token(token_endpoint, data, timeout))
    except (KeyError, TypeError, ValueError) as e:
        raise AuthError(f"Could not get token: {type(e).__name__}") from e


def get_token(
    token_endpoint: str, client_id: str, client_secret: str, timeout: int = 10
) -> Token:
    """OIDC client-credentials grant. Returns the token with its expiry."""
    return _request_token(
        token_endpoint,
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout,
    )


def get_password_token(
    token_endpoint: str,
    client_id: str,
    username: str,
    password: str,
    client_secret: str | None = None,
    timeout: int = 10,
) -> Token:
    """OIDC password grant: log in as a user. Returns the token with its expiry.

    ``client_id`` is the client the token is for (it needs "Direct access
    grants" enabled); ``client_secret`` is only for a confidential client.
    """
    data = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }
    if client_secret:
        data["client_secret"] = client_secret
    return _request_token(token_endpoint, data, timeout)


def fetch_token(
    token_endpoint: str, client_id: str, client_secret: str, timeout: int = 10
) -> str:
    """Like ``get_token`` but returns just the access token string."""
    return get_token(token_endpoint, client_id, client_secret, timeout).access_token
