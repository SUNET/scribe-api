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

"""Exceptions raised by the Scribe API client."""


class ScribeError(Exception):
    """Any failure talking to the API. ``status`` is the HTTP status, if any."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class AuthError(ScribeError):
    """The token could not be fetched or was refused."""


class NotFound(ScribeError):
    """The job does not exist (or is not the caller's)."""


class QuotaExceeded(ScribeError):
    """The user's transcription quota is used up (HTTP 403 on start)."""


class RateLimited(ScribeError):
    """The API kept answering 429 after the client's retries."""


class JobFailed(ScribeError):
    """The job ended in status "failed". ``job`` is the job as returned."""

    def __init__(self, message: str, job: dict):
        super().__init__(message)
        self.job = job
