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

import time
from dataclasses import dataclass

import requests

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


def get_token(
    token_endpoint: str, client_id: str, client_secret: str, timeout: int = 10
) -> Token:
    """OIDC client-credentials grant. Returns the token with its expiry."""
    try:
        response = requests.post(
            token_endpoint,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        body = response.json()
        expires_in = body.get("expires_in")
        return Token(
            access_token=body["access_token"],
            expires_at=(
                time.monotonic() + float(expires_in)
                if expires_in is not None
                else None
            ),
        )
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        # Not the response: its body can echo the request.
        raise AuthError(f"Could not get token: {type(e).__name__}") from e


def fetch_token(
    token_endpoint: str, client_id: str, client_secret: str, timeout: int = 10
) -> str:
    """Like ``get_token`` but returns just the access token string."""
    return get_token(token_endpoint, client_id, client_secret, timeout).access_token
