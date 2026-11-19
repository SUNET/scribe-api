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

DEFAULT_API_URL = "https://scribe.sunet.se/api/v1"

# Where ``login`` signs users in, and the public client it uses (no secret).
# Override with SCRIBE_OIDC_ISSUER and SCRIBE_OIDC_CLIENT_ID.
DEFAULT_OIDC_ISSUER = "https://keycloak-1.transcribe.sunet.se/realms/transcriber"
DEFAULT_OIDC_CLIENT_ID = "automations"

# Full names the worker has a model for (scribe-ui settings.WHISPER_LANGUAGES).
# A code such as "sv" makes the worker raise before it can report failure,
# leaving the job in_progress forever.
LANGUAGES = (
    "Swedish",
    "English",
    "Norwegian",
    "Finnish",
    "Danish",
    "French",
    "Spanish",
    "Portuguese",
    "German",
    "Italian",
    "Dutch",
    "Russian",
    "Ukrainian",
    "Icelandic",
)

# ISO 639-1 codes, accepted as shorthands. The worker only understands the full
# names above, so the client translates before sending. Norwegian has no
# ISO 639-1 code of its own for Bokmal/Nynorsk, so "nb" and "nn" map to it too.
LANGUAGE_CODES = {
    "sv": "Swedish",
    "en": "English",
    "no": "Norwegian",
    "nb": "Norwegian",
    "nn": "Norwegian",
    "fi": "Finnish",
    "da": "Danish",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "de": "German",
    "it": "Italian",
    "nl": "Dutch",
    "ru": "Russian",
    "uk": "Ukrainian",
    "is": "Icelandic",
}


def resolve_language(language: str) -> str:
    """The full language name for a full name or an ISO 639-1 code.

    Case does not matter ("sv", "SV", "swedish" all give "Swedish").
    Raises ``ValueError`` for anything the worker has no model for.
    """
    key = language.strip().lower()
    if key in LANGUAGE_CODES:
        return LANGUAGE_CODES[key]
    for name in LANGUAGES:
        if name.lower() == key:
            return name
    raise ValueError(
        f"unknown language {language!r}; use one of {', '.join(LANGUAGES)} "
        f"or an ISO 639-1 code ({', '.join(LANGUAGE_CODES)})"
    )


# Starting a job takes these uppercase (as the UI sends them); reading a
# result takes them lowercase. The client converts either way.
OUTPUT_FORMATS = ("TXT", "SRT")

# Job statuses. A job moves uploaded -> pending -> in_progress -> one of
# FINISHED.
FINISHED = ("completed", "failed")
