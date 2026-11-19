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

"""Python client for the Sunet Scribe API.

    from scribe import ScribeClient

    with ScribeClient.from_env() as scribe:
        scribe.check()                                  # GET /me
        job = scribe.transcribe("meeting.mp3", language="Swedish")
        print(scribe.result(job["uuid"], "srt"))
"""

from .auth import Token, fetch_token, get_password_token, get_token
from .client import ScribeClient
from .constants import (
    DEFAULT_API_URL,
    FINISHED,
    LANGUAGE_CODES,
    LANGUAGES,
    OUTPUT_FORMATS,
    VERBATIM_LANGUAGES,
    resolve_language,
)
from .signin import login, logout
from .errors import (
    AuthError,
    JobFailed,
    NotFound,
    QuotaExceeded,
    RateLimited,
    ScribeError,
)
from .throttle import Throttle

__all__ = [
    "AuthError",
    "DEFAULT_API_URL",
    "FINISHED",
    "JobFailed",
    "LANGUAGES",
    "LANGUAGE_CODES",
    "NotFound",
    "OUTPUT_FORMATS",
    "QuotaExceeded",
    "RateLimited",
    "ScribeClient",
    "ScribeError",
    "Throttle",
    "Token",
    "VERBATIM_LANGUAGES",
    "fetch_token",
    "get_password_token",
    "get_token",
    "login",
    "logout",
    "resolve_language",
]
