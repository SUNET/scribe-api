#!/usr/bin/env python3
"""Transcribe a batch of media files with the Sunet Scribe API.

All files are uploaded first, one by one. Only when every upload is done are
the transcriptions started, so the jobs run on the server at the same time.
Then all jobs are polled, and each result is written next to its media file
as soon as that job completes.

Usage:
    python examples/transcribe_batch.py recordings/            # a folder
    python examples/transcribe_batch.py a.mp3 b.mp4 c.wav      # some files
    python examples/transcribe_batch.py recordings/ --language en --format txt

Needs OIDC_TOKEN_ENDPOINT, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET and
SCRIBE_ENCRYPTION_PASSWORD in the environment.
"""

import argparse
import sys
import time
from pathlib import Path

from scribe import (
    FINISHED,
    resolve_language,
    QuotaExceeded,
    ScribeClient,
    ScribeError,
)

MEDIA_SUFFIXES = {
    ".mp3", ".mp4", ".m4a", ".wav", ".flac", ".ogg", ".opus",
    ".webm", ".mkv", ".mov", ".aac", ".wma",
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def language_arg(value: str) -> str:
    try:
        return resolve_language(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def collect(inputs: list[str]) -> list[Path]:
    """Expand folders into their media files, keep named files as given."""
    files: list[Path] = []
    for item in inputs:
        path = Path(item)
        if path.is_dir():
            files += sorted(
                p for p in path.iterdir() if p.suffix.lower() in MEDIA_SUFFIXES
            )
        elif path.is_file():
            files.append(path)
        else:
            log(f"Skipping, not found: {item}")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("inputs", nargs="+", help="media files and/or folders")
    parser.add_argument(
        "--language",
        default="Swedish",
        type=language_arg,
        help="full name or ISO 639-1 code, e.g. Swedish or sv",
    )
    parser.add_argument("--format", default="srt", choices=["txt", "srt"])
    parser.add_argument("--poll", type=int, default=10, help="seconds between polls")
    parser.add_argument("--max-wait", type=int, default=7200, help="seconds, in total")
    parser.add_argument(
        "--overwrite", action="store_true", help="redo files that already have output"
    )
    args = parser.parse_args()

    files = collect(args.inputs)
    if not files:
        print("No media files found", file=sys.stderr)
        return 2

    todo = []
    for path in files:
        out = path.with_suffix(f".{args.format}")
        if out.exists() and not args.overwrite:
            log(f"Skipping {path.name}: {out.name} exists (use --overwrite)")
        else:
            todo.append(path)
    if not todo:
        return 0

    failures: dict[str, str] = {}
    running: dict[str, Path] = {}  # job id -> media file

    with ScribeClient.from_env() as scribe:
        try:
            scribe.check()

            # 1. Upload every file, one at a time. Nothing is started yet.
            uploaded: dict[str, Path] = {}  # job id -> media file
            for i, path in enumerate(todo, 1):
                prefix = f"({i}/{len(todo)}) {path.name}"
                try:
                    log(f"{prefix}: uploading")
                    uploaded[scribe.upload(str(path))] = path
                except ScribeError as e:
                    failures[path.name] = str(e)
                    log(f"{prefix}: upload failed, {e}")
            log(f"Uploaded {len(uploaded)}/{len(todo)} files")

            # 2. Start them all.
            for i, (job_id, path) in enumerate(list(uploaded.items()), 1):
                prefix = f"({i}/{len(uploaded)}) {path.name}"
                try:
                    scribe.start(
                        job_id, language=args.language, output_format=args.format.upper()
                    )
                    running[job_id] = path
                    log(f"{prefix}: started, job {job_id}")
                except QuotaExceeded:
                    # Uploaded but never started: remove them instead of
                    # leaving them behind as "uploaded".
                    log("Quota used up, not starting the rest")
                    for rest_id, rest in list(uploaded.items())[i - 1 :]:
                        failures[rest.name] = "not started: quota used up"
                        try:
                            scribe.delete(rest_id)
                        except ScribeError as e:
                            log(f"{rest.name}: could not delete job {rest_id}, {e}")
                    break
                except ScribeError as e:
                    failures[path.name] = str(e)
                    log(f"{prefix}: start failed, {e}")

            # 2. Poll every running job until all are finished.
            deadline = time.monotonic() + args.max_wait
            total = len(running)
            while running:
                for job_id, path in list(running.items()):
                    try:
                        job = scribe.job(job_id)
                    except ScribeError as e:
                        failures[path.name] = str(e)
                        del running[job_id]
                        log(f"{path.name}: lost track of job, {e}")
                        continue

                    if job["status"] not in FINISHED:
                        continue
                    del running[job_id]

                    if job["status"] == "completed":
                        out = path.with_suffix(f".{args.format}")
                        out.write_text(
                            scribe.result(job_id, args.format), encoding="utf-8"
                        )
                        log(f"{path.name}: done -> {out.name}")
                    else:
                        failures[path.name] = job.get("error") or "failed"
                        log(f"{path.name}: FAILED, {failures[path.name]}")

                if not running:
                    break
                if time.monotonic() >= deadline:
                    for job_id, path in running.items():
                        failures[path.name] = f"still running after {args.max_wait}s"
                    break
                log(f"Waiting: {total - len(running)}/{total} finished")
                time.sleep(args.poll)
        except (ScribeError, ValueError) as e:
            print(e, file=sys.stderr)
            return 1

    if failures:
        print(f"\n{len(failures)} problem(s):", file=sys.stderr)
        for name, reason in failures.items():
            print(f"  {name}: {reason}", file=sys.stderr)
        return 1
    log("All done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
