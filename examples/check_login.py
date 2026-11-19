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

"""Verify that login works, and show who the API thinks you are.

    python examples/check_login.py

Authenticates with SCRIBE_JWT (a JWT from the web interface) if set; else
as a Keycloak user if OIDC_USERNAME and OIDC_PASSWORD are set (with
OIDC_TOKEN_ENDPOINT and OIDC_CLIENT_ID); otherwise with OIDC_TOKEN_ENDPOINT,
OIDC_CLIENT_ID and OIDC_CLIENT_SECRET.
Reads SCRIBE_API_URL if set. Exits 0 if the API accepts the token, 1 if not.
"""

import os
import sys

from scribe import AuthError, ScribeClient, ScribeError
from scribe.display import describe_user, who


def main() -> int:
    if os.environ.get("SCRIBE_JWT"):
        method = "JWT"
    elif os.environ.get("OIDC_USERNAME") or os.environ.get("OIDC_PASSWORD"):
        method = "OIDC user password"
    elif not any(k.startswith("OIDC_") for k in os.environ):
        method = "saved login"
    else:
        method = "OIDC client credentials"

    try:
        with ScribeClient.from_env() as scribe:
            user = scribe.check()
    except AuthError as e:
        print(f"Login failed ({method}): {e}", file=sys.stderr)
        return 1
    except ScribeError as e:
        print(f"Could not reach the API: {e}", file=sys.stderr)
        return 1

    print(f"Login OK ({method}): signed in as {who(user)}\n")
    print(describe_user(user))
    return 0


if __name__ == "__main__":
    sys.exit(main())
