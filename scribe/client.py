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

"""Client for the Sunet Scribe API."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests

from .auth import Token, get_password_token, get_token, require_https
from .signin import load_login, saved_login_token_source
from .constants import DEFAULT_API_URL, FINISHED, OUTPUT_FORMATS, resolve_language
from .throttle import Throttle
from .errors import (
    AuthError,
    JobFailed,
    NotFound,
    QuotaExceeded,
    RateLimited,
    ScribeError,
)


class ScribeClient:
    """Thin wrapper around the Scribe API.

    ``token`` is a bearer token string (such as a JWT from the web
    interface), a ``Token``, or a zero-argument
    callable returning either. A callable is called to get the first token and
    again only once that token has expired (``Token.expires_at``, from the
    provider's ``expires_in``), so a long ``wait()`` outlives it without
    fetching a token per request.

    If the expiry is not known (a plain string, or no ``expires_in``) the
    token is used until the API answers 401, then fetched once more and the
    request retried. A 401 on a token known to be unexpired is not retried: a
    new one would be refused the same way.

    Requests are throttled to ``requests_per_second`` on average (bursts of up
    to ``burst``, default the rate rounded down), shared by every thread using
    the client; pass ``None`` to turn it off. If the API answers 429 anyway,
    the request is retried up to ``max_retries`` times, waiting as long as the
    ``Retry-After`` header says (else 1, 2, 4... seconds, at most
    ``MAX_RETRY_WAIT``). A 429 means the request was not processed, so
    retrying is safe for every method. Out of retries it raises
    ``RateLimited``.

    File names and results are encrypted to the user's key; set
    ``encryption_password`` to read them. Without it you get ciphertext back,
    not an error.
    """

    # Seconds before expiry at which a token counts as expired, so it does
    # not run out between being checked and being used.
    TOKEN_LEEWAY = 30.0

    # Longest the client will sleep on one 429, whatever Retry-After says,
    # and the fastest ``wait()`` will poll whatever it is asked.
    MAX_RETRY_WAIT = 60.0
    MIN_POLL_SECONDS = 1.0

    def __init__(
        self,
        token: str | Token | Callable[[], str | Token],
        base_url: str = DEFAULT_API_URL,
        encryption_password: str | None = None,
        requests_per_second: float | None = 5.0,
        burst: int | None = None,
        max_retries: int = 3,
    ):
        self.base_url = require_https(base_url).rstrip("/")
        self.encryption_password = encryption_password
        self._token_source = token if callable(token) else None
        self._token: Token | None = (
            None
            if callable(token)
            else token if isinstance(token, Token) else Token.from_jwt(token)
        )
        self._session = requests.Session()
        self._throttle = (
            Throttle(requests_per_second, burst) if requests_per_second else None
        )
        self.max_retries = max_retries

    @classmethod
    def from_login(cls) -> "ScribeClient":
        """Build a client from the login saved by ``python -m scribe login``.

        Reads SCRIBE_API_URL and SCRIBE_ENCRYPTION_PASSWORD if set. Raises
        ``AuthError`` if nobody has signed in.
        """
        return cls(
            token=saved_login_token_source(),
            base_url=os.environ.get("SCRIBE_API_URL", DEFAULT_API_URL),
            encryption_password=os.environ.get("SCRIBE_ENCRYPTION_PASSWORD"),
        )

    @classmethod
    def from_env(cls) -> "ScribeClient":
        """Build a client from the environment.

        Uses SCRIBE_JWT (a JWT from the web interface) if set. Else, if
        OIDC_USERNAME or OIDC_PASSWORD is set, logs in as that user (password
        grant; needs OIDC_TOKEN_ENDPOINT and OIDC_CLIENT_ID, and
        OIDC_CLIENT_SECRET for a confidential client). Otherwise needs
        OIDC_TOKEN_ENDPOINT, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET. If none
        of the OIDC variables are set, falls back to the saved login (see
        ``from_login``).
        Reads SCRIBE_API_URL and SCRIBE_ENCRYPTION_PASSWORD if set.
        """
        if os.environ.get("SCRIBE_JWT"):
            return cls(
                token=os.environ["SCRIBE_JWT"],
                base_url=os.environ.get("SCRIBE_API_URL", DEFAULT_API_URL),
                encryption_password=os.environ.get("SCRIBE_ENCRYPTION_PASSWORD"),
            )

        if os.environ.get("OIDC_USERNAME") or os.environ.get("OIDC_PASSWORD"):
            missing = [
                k
                for k in (
                    "OIDC_TOKEN_ENDPOINT",
                    "OIDC_CLIENT_ID",
                    "OIDC_USERNAME",
                    "OIDC_PASSWORD",
                )
                if k not in os.environ
            ]
            if missing:
                raise AuthError(f"Not set: {', '.join(missing)}")
            return cls(
                token=lambda: get_password_token(
                    os.environ["OIDC_TOKEN_ENDPOINT"],
                    os.environ["OIDC_CLIENT_ID"],
                    os.environ["OIDC_USERNAME"],
                    os.environ["OIDC_PASSWORD"],
                    os.environ.get("OIDC_CLIENT_SECRET"),
                ),
                base_url=os.environ.get("SCRIBE_API_URL", DEFAULT_API_URL),
                encryption_password=os.environ.get("SCRIBE_ENCRYPTION_PASSWORD"),
            )

        oidc = ("OIDC_TOKEN_ENDPOINT", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET")
        if not any(k in os.environ for k in oidc) and load_login() is not None:
            return cls.from_login()

        missing = [
            k
            for k in oidc
            if k not in os.environ
        ]
        if missing:
            hint = (
                " (or sign in with `python -m scribe login`)"
                if len(missing) == len(oidc)
                else ""
            )
            raise AuthError(f"Not set: {', '.join(missing)}{hint}")

        return cls(
            token=lambda: get_token(
                os.environ["OIDC_TOKEN_ENDPOINT"],
                os.environ["OIDC_CLIENT_ID"],
                os.environ["OIDC_CLIENT_SECRET"],
            ),
            base_url=os.environ.get("SCRIBE_API_URL", DEFAULT_API_URL),
            encryption_password=os.environ.get("SCRIBE_ENCRYPTION_PASSWORD"),
        )

    def __enter__(self) -> "ScribeClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    # -- plumbing ----------------------------------------------------------

    def _refresh_token(self) -> None:
        fetched = self._token_source()
        self._token = (
            fetched if isinstance(fetched, Token) else Token.from_jwt(fetched)
        )

    def _bearer(self, force: bool = False) -> dict[str, str]:
        """Authorization header, fetching a token if there is none, it has
        expired, or ``force`` (a 401 on a token of unknown expiry)."""
        if self._token_source is not None and (
            force or self._token is None or self._token.expired(self.TOKEN_LEEWAY)
        ):
            self._refresh_token()
        elif self._token_source is None and self._token.expired():
            raise AuthError("The JWT has expired; get a new one")
        return {"Authorization": f"Bearer {self._token.access_token}"}

    def _retry_on_401(self) -> bool:
        """Whether a 401 is worth one more try with a new token."""
        return (
            self._token_source is not None
            and self._token is not None
            and self._token.expires_at is None
        )

    def _request(
        self, method: str, path: str, timeout: int = 30, **kwargs: Any
    ) -> requests.Response:
        url = f"{self.base_url}{path}"

        # An open file cannot be resent as is, so remember where it started.
        files = kwargs.get("files") or {}
        positions = {name: f[1].tell() for name, f in files.items()}

        auth_retried = False
        rate_retries = 0

        while True:
            if self._throttle:
                self._throttle.acquire()

            try:
                response = self._session.request(
                    method,
                    url,
                    headers=self._bearer(force=auth_retried),
                    timeout=timeout,
                    **kwargs,
                )
            except requests.RequestException as e:
                raise ScribeError(f"{method} {path} failed: {e}") from e

            if (
                response.status_code == 401
                and not auth_retried
                and self._retry_on_401()
            ):
                auth_retried = True
            elif response.status_code == 429 and rate_retries < self.max_retries:
                time.sleep(self._retry_wait(response, rate_retries))
                rate_retries += 1
            else:
                break

            for name, pos in positions.items():
                files[name][1].seek(pos)

        if not response.ok:
            try:
                detail = response.json()
            except ValueError:
                detail = response.text[:200]
            message = f"{method} {path} -> {response.status_code}: {detail}"
            if response.status_code == 401:
                raise AuthError(message, status=401)
            if response.status_code == 404:
                raise NotFound(message, status=404)
            if response.status_code == 429:
                raise RateLimited(message, status=429)
            raise ScribeError(message, status=response.status_code)
        return response

    def _retry_wait(self, response: requests.Response, retries_done: int) -> float:
        """Seconds to wait before retrying a 429."""
        try:
            wait = float(response.headers["Retry-After"])
        except (KeyError, ValueError):
            # Absent, or an HTTP date: back off 1, 2, 4... seconds.
            wait = float(2**retries_done)
        return min(max(wait, 0.0), self.MAX_RETRY_WAIT)

    def _password(self, password: str | None) -> str | None:
        return password if password is not None else self.encryption_password

    def _password_body(self) -> dict | None:
        return (
            {"encryption_password": self.encryption_password}
            if self.encryption_password
            else None
        )

    # -- account -----------------------------------------------------------

    def me(self) -> dict:
        """GET /me: the current user."""
        return self._request("GET", "/me", timeout=10).json()["result"]

    def check(self) -> dict:
        """Verify the token works. Same as ``me()``; raises if it does not."""
        return self.me()

    def set_encryption_password(self, password: str | None = None) -> None:
        """Enable encryption by setting a password.

        The server makes a new RSA key pair protected by the password. It
        cannot be recovered, and setting it again replaces the key pair and
        makes everything encrypted with the old one unreadable. So this
        refuses if one is already set.
        """
        password = self._password(password)
        if not password:
            raise ScribeError("Encryption password must not be empty")
        if self.me().get("encryption_settings"):
            raise ScribeError(
                "An encryption password is already set; "
                "refusing to replace the key pair"
            )
        self._request(
            "PUT",
            "/me",
            timeout=60,
            json={"encryption": True, "encryption_password": password},
        )
        self.encryption_password = password

    def verify_encryption_password(self, password: str | None = None) -> bool:
        """True if the password opens the user's private key."""
        try:
            self._request(
                "PUT",
                "/me",
                json={
                    "verify_password": True,
                    "encryption_password": self._password(password),
                },
            )
        except ScribeError as e:
            if e.status == 403:
                return False
            raise
        return True

    # -- jobs --------------------------------------------------------------

    def jobs(self) -> list[dict]:
        """All the user's transcription jobs, file names decrypted."""
        response = self._request("GET", "/transcriber", json=self._password_body())
        return response.json()["result"]["jobs"]

    def job(self, job_id: str) -> dict:
        """One job, file name decrypted."""
        response = self._request(
            "GET",
            "/transcriber",
            params={"job_id": job_id},
            json=self._password_body(),
        )
        result = response.json()["result"]
        if not isinstance(result, dict) or "uuid" not in result:
            raise NotFound(f"Job {job_id} not found", status=404)
        return result

    def upload(self, path: str) -> str:
        """Upload a media file. Returns the job UUID (status "uploaded").

        Streamed from disk and encrypted server side as it arrives. Does not
        start the job; see ``start()``.
        """
        with open(path, "rb") as f:
            response = self._request(
                "POST",
                "/transcriber",
                timeout=600,
                files={"file": (os.path.basename(path), f)},
            )
        return response.json()["result"]["uuid"]

    def start(
        self,
        job_id: str,
        language: str = "Swedish",
        speakers: int = 0,
        output_format: str = "TXT",
        verbatim: bool = False,
    ) -> dict:
        """Queue an uploaded job for transcription (status "pending").

        ``language`` is a full name ("Swedish") or an ISO 639-1 code ("sv");
        the worker only knows the full names, so a code is translated here.
        ``verbatim=True`` selects the strict model that keeps filler words and
        repetitions; see ``VERBATIM_LANGUAGES``.
        """
        language = resolve_language(language, verbatim)
        output_format = output_format.upper()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError(f"output_format must be one of {OUTPUT_FORMATS}")

        try:
            response = self._request(
                "PUT",
                f"/transcriber/{job_id}",
                json={
                    "language": language,
                    "speakers": speakers,
                    "output_format": output_format,
                    "encryption_password": self.encryption_password,
                },
            )
        except ScribeError as e:
            if e.status == 403:
                raise QuotaExceeded(str(e), status=403) from e
            raise
        return response.json()["result"]

    def wait(
        self, job_id: str, poll_seconds: int = 10, max_wait_seconds: int = 3600
    ) -> dict:
        """Poll until the job is completed or failed. Returns the job."""
        poll_seconds = max(poll_seconds, self.MIN_POLL_SECONDS)
        deadline = time.monotonic() + max_wait_seconds
        while True:
            job = self.job(job_id)
            if job["status"] in FINISHED:
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Job {job_id} still {job['status']} after {max_wait_seconds}s"
                )
            time.sleep(poll_seconds)

    def result(
        self,
        job_id: str,
        output_format: str = "txt",
        password: str | None = None,
    ) -> str:
        """The finished transcription as "txt" or "srt", decrypted."""
        password = self._password(password)
        if not password:
            raise ScribeError("An encryption password is needed to read results")
        response = self._request(
            "GET",
            f"/transcriber/{job_id}/result/{output_format.lower()}",
            timeout=60,
            json={"encryption_password": password},
        )
        return response.json()["result"]

    def words(self, job_id: str, password: str | None = None) -> str:
        """Per-word timings as a JSON string, or "" if the job has none."""
        response = self._request(
            "GET",
            f"/transcriber/{job_id}/words",
            timeout=60,
            json={"encryption_password": self._password(password)},
        )
        return response.json()["result"]

    def delete(self, job_id: str) -> None:
        """Delete a job and its files."""
        self._request("DELETE", f"/transcriber/{job_id}")

    def transcribe(
        self,
        path: str,
        language: str = "Swedish",
        speakers: int = 0,
        output_format: str = "TXT",
        poll_seconds: int = 10,
        max_wait_seconds: int = 3600,
        verbatim: bool = False,
    ) -> dict:
        """Upload, start and wait. Returns the finished job.

        Raises ``JobFailed`` if the job fails. Fetch the text with
        ``result()``.
        """
        job_id = self.upload(path)
        self.start(job_id, language, speakers, output_format, verbatim)
        job = self.wait(job_id, poll_seconds, max_wait_seconds)
        if job["status"] != "completed":
            raise JobFailed(f"Job {job_id} failed: {job.get('error')}", job)
        return job
