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

"""Showing API answers to people."""

from typing import Any

# What to call a user, best first.
_IDENTITY_KEYS = ("username", "preferred_username", "email", "name", "user_id")


# Fields whose names contain one of these are never shown: keys, secrets and
# the like. (``/me`` includes the user's encryption key pair.)
_HIDDEN = ("key", "secret", "password", "token", "salt", "hash")


def _hidden(key: Any) -> bool:
    return any(word in str(key).lower() for word in _HIDDEN)


def _label(key: str) -> str:
    return key.replace("_", " ").capitalize()


def _sep(text: str) -> str:
    """Space before a one-line value, none before an indented block."""
    return text if text.startswith("\n") else f" {text}"


def _value(value: Any, indent: int = 0) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        pad = " " * (indent + 2)
        return "".join(
            f"\n{pad}{_label(str(k))}:{_sep(_value(v, indent + 2))}"
            for k, v in value.items()
            if v not in (None, "", [], {}) and not _hidden(k)
        )
    if isinstance(value, (list, tuple)):
        return ", ".join(_value(v, indent) for v in value)
    return str(value)


def describe_user(user: dict[str, Any]) -> str:
    """The ``/me`` answer as plain lines: ``Name: ...``, ``User id: ...``.

    Empty fields and anything that looks like a key or secret are left
    out. Works whatever fields the API sends.
    """
    lines = [
        f"{_label(str(k))}:{_sep(_value(v))}"
        for k, v in user.items()
        if v not in (None, "", [], {}) and not _hidden(k)
    ]
    return "\n".join(lines) or "(the API returned no details)"


def who(user: dict[str, Any]) -> str:
    """A short name for the user, e.g. for 'Signed in as ...'."""
    for key in _IDENTITY_KEYS:
        if user.get(key):
            return str(user[key])
    return "unknown user"
