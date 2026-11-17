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

# Starting a job takes these uppercase (as the UI sends them); reading a
# result takes them lowercase. The client converts either way.
OUTPUT_FORMATS = ("TXT", "SRT")

# Job statuses. A job moves uploaded -> pending -> in_progress -> one of
# FINISHED.
FINISHED = ("completed", "failed")
