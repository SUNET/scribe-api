#!/usr/bin/env python3
"""Transcribe a media file with the Sunet Scribe API, printing each step.

Usage: python examples/transcribe.py meeting.mp3 [Language|code] [txt|srt]

Needs OIDC_TOKEN_ENDPOINT, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and
SCRIBE_ENCRYPTION_PASSWORD in the environment.
"""

import sys
import time
from pathlib import Path

from scribe import (
    FINISHED,
    QuotaExceeded,
    ScribeClient,
    ScribeError,
)

POLL_SECONDS = 5
MAX_WAIT_SECONDS = 3600


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    language = sys.argv[2] if len(sys.argv) > 2 else "Swedish"
    fmt = sys.argv[3] if len(sys.argv) > 3 else "srt"

    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 2

    with ScribeClient.from_env() as scribe:
        try:
            log("Checking credentials")
            scribe.check()

            size_mb = path.stat().st_size / 1_000_000
            log(f"Uploading {path.name} ({size_mb:.1f} MB)")
            job_id = scribe.upload(str(path))
            log(f"Uploaded, job {job_id}")

            log(f"Starting: language={language}, format={fmt.upper()}")
            started_job = scribe.start(
                job_id, language=language, output_format=fmt.upper()
            )
            log(f"Server answered: {started_job}")

            started = time.monotonic()
            last_status = None
            while True:
                job = scribe.job(job_id)
                status = job["status"]
                elapsed = int(time.monotonic() - started)
                if status != last_status:
                    log(f"Status: {status}")
                    last_status = status
                else:
                    log(f"  still {status} ({elapsed}s)")
                if status in FINISHED:
                    break
                if elapsed >= MAX_WAIT_SECONDS:
                    print(f"Gave up after {elapsed}s; job {job_id} still {status}",
                          file=sys.stderr)
                    return 1
                time.sleep(POLL_SECONDS)

            if status != "completed":
                print(f"Job failed: {job.get('error')}", file=sys.stderr)
                return 1

            log("Fetching result")
            text = scribe.result(job_id, fmt.lower())
        except QuotaExceeded:
            print("Quota used up", file=sys.stderr)
            return 1
        except (ScribeError, ValueError) as e:
            print(e, file=sys.stderr)
            return 1

    out = path.with_suffix(f".{fmt.lower()}")
    out.write_text(text, encoding="utf-8")
    log(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
