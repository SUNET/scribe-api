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
    "Northern Sámi (Experimental)",
)

# Languages with a strict model that keeps filler words, repetitions and
# unfinished sentences. The worker keys it "<language> (verbatim)".
VERBATIM_LANGUAGES = ("Swedish", "English", "Norwegian")
VERBATIM_SUFFIX = " (verbatim)"

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
    "se": "Northern Sámi (Experimental)",
}


def resolve_language(language: str, verbatim: bool = False) -> str:
    """The worker's language key for a full name or an ISO 639-1 code.

    Case does not matter ("sv", "SV", "swedish" all give "Swedish").
    With ``verbatim=True`` the key of the strict model is returned
    ("Swedish (verbatim)"). The worker's exact key is accepted too and implies
    ``verbatim=True``. Raises ``ValueError`` for anything the worker has
    no model for, including verbatim for a language not in
    ``VERBATIM_LANGUAGES``.
    """
    key = language.strip().lower()
    if key.endswith(VERBATIM_SUFFIX.lower()):
        # The worker's own key, "Swedish (verbatim)".
        key = key[: -len(VERBATIM_SUFFIX)].rstrip()
        verbatim = True
    name = LANGUAGE_CODES.get(key)
    if name is None:
        for candidate in LANGUAGES:
            if candidate.lower() == key:
                name = candidate
                break
    if name is None:
        raise ValueError(
            f"unknown language {language!r}; use one of {', '.join(LANGUAGES)} "
            f"or an ISO 639-1 code ({', '.join(LANGUAGE_CODES)})"
        )
    if verbatim:
        if name not in VERBATIM_LANGUAGES:
            raise ValueError(
                f"no verbatim model for {name!r}; "
                f"verbatim is available for {', '.join(VERBATIM_LANGUAGES)}"
            )
        return name + VERBATIM_SUFFIX
    return name


# Starting a job takes these uppercase (as the UI sends them); reading a
# result takes them lowercase. The client converts either way.
OUTPUT_FORMATS = ("TXT", "SRT")

# Job statuses. A job moves uploaded -> pending -> in_progress -> one of
# FINISHED.
FINISHED = ("completed", "failed")
