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

"""Command line: ``python -m scribe login | logout | whoami``."""

import sys

from .client import ScribeClient
from .display import who
from .errors import ScribeError
from .signin import login, logout, token_path

USAGE = """usage: python -m scribe <command>

  login    sign in (opens a code and URL to use in a browser)
  logout   forget the saved login
  whoami   print the username you are signed in as
"""


def main(argv: list[str]) -> int:
    command = argv[0] if argv else ""
    try:
        if command == "login":
            login()
            with ScribeClient.from_login() as scribe:
                user = scribe.me()
            print(f"Signed in as {who(user)}.")
            print(f"Login saved in {token_path()}")
        elif command == "logout":
            print("Signed out." if logout() else "Not signed in.")
        elif command == "whoami":
            with ScribeClient.from_login() as scribe:
                user = scribe.me()
            print(who(user))
        else:
            print(USAGE, file=sys.stderr)
            return 2
    except ScribeError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
