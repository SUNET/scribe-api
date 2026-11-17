# Scribe API client

A small Python client for the Sunet Scribe API: upload a recording, start a
transcription, wait for it, and fetch the result.

Requires Python 3.10+ and [`requests`](https://pypi.org/project/requests/).

```python
from scribe_api import ScribeClient

with ScribeClient.from_env() as scribe:
    scribe.check()                                         # GET /me
    job = scribe.transcribe("meeting.mp3", language="Swedish", output_format="SRT")
    print(scribe.result(job["uuid"], "srt"))
```

## Install

```bash
pip install git+https://github.com/SUNET/scribe-api   # or: pip install -e . in a checkout
```

Import it as `scribe_api`.

## Setup

The client authenticates with an OIDC client-credentials grant. Set:

| Variable | Needed | Meaning |
|---|---|---|
| `OIDC_TOKEN_ENDPOINT` | yes | Token endpoint of the OIDC provider |
| `OIDC_CLIENT_ID` | yes | Client id |
| `OIDC_CLIENT_SECRET` | yes | Client secret |
| `SCRIBE_API_URL` | no | Defaults to `https://scribe.sunet.se/api/v1` |
| `SCRIBE_ENCRYPTION_PASSWORD` | for results | The user's encryption password |

```python
scribe = ScribeClient.from_env()
```

Or pass things yourself. `token` is a bearer token string, a `Token`, or a
function returning either.

```python
from scribe_api import ScribeClient, get_token

scribe = ScribeClient(
    token=lambda: get_token(endpoint, client_id, client_secret),
    base_url="https://scribe.sunet.se/api/v1",
    encryption_password="...",
)
```

**Tokens are fetched only when needed.** `get_token()` returns a `Token` with
the expiry from the provider's `expires_in`. The client fetches the first token
on first use, reuses it for every request, and fetches a new one only once it
has expired (counting the last 30 seconds, `ScribeClient.TOKEN_LEEWAY`, as
expired so it cannot run out mid-request). A long `wait()` therefore outlives
the token without fetching one per request.

If the expiry is not known (you passed a plain string, or the provider sent no
`expires_in`), the token is used until the API answers 401, then fetched once
more and the request retried. A fixed string cannot be refreshed, so a 401
raises `AuthError`. A 401 on a token that is known to be unexpired is not
retried either: a new one would be refused the same way. (`fetch_token()` still
exists and returns just the string, but a string carries no expiry.)

Use it as a context manager (or call `close()`) to release the connection.

## Throttling

The client limits itself so a script cannot hammer the API.

```python
ScribeClient.from_env()                                   # 5 requests/second
ScribeClient(token, requests_per_second=2, burst=4)       # slower
ScribeClient(token, requests_per_second=None)             # off
```

- **Rate:** at most `requests_per_second` on average, with bursts of up to
  `burst` (default the rate rounded down). Every call counts, including each
  poll in `wait()`. The limit is shared by all threads using one client, so
  threads that share a client share the budget. Separate clients, or separate
  processes, each have their own budget.
- **Polling:** `wait()` never polls faster than once a second
  (`ScribeClient.MIN_POLL_SECONDS`), whatever `poll_seconds` says.
- **429 Too Many Requests:** if the API answers 429 anyway, the client waits
  and retries, up to `max_retries` times (default 3). It waits as long as the
  `Retry-After` header says, or 1, 2, 4 seconds if there is none, and never
  more than 60 seconds (`ScribeClient.MAX_RETRY_WAIT`). A 429 means the request
  was not processed, so retrying is safe for uploads and starts too. Out of
  retries, it raises `RateLimited`.

This is politeness on the client side. It does not replace limits on the server,
and anyone can turn it off or write their own client.

## How a job works

Uploading does **not** start a transcription. A job moves through:

```
uploaded --start()--> pending --worker--> in_progress --> completed | failed
```

`upload()` leaves the job `uploaded`, `start()` queues it, a worker picks it
up, and `wait()` returns once it is `completed` or `failed`.
`transcribe()` does all three.

### Step by step

```python
job_id = scribe.upload("meeting.mp3")
scribe.start(job_id, language="Swedish", speakers=0, output_format="TXT")
job = scribe.wait(job_id, poll_seconds=10, max_wait_seconds=3600)

if job["status"] == "completed":
    text = scribe.result(job_id, "txt")
```

## Methods

| Method | Does |
|---|---|
| `me()` / `check()` | `GET /me`. Returns the user; raises if the token is refused |
| `upload(path)` | Upload a media file. Returns the job UUID |
| `start(job_id, language, speakers, output_format)` | Queue an uploaded job |
| `wait(job_id, poll_seconds, max_wait_seconds)` | Poll until finished. Returns the job. `TimeoutError` if it takes too long |
| `transcribe(path, ...)` | Upload, start, wait. Raises `JobFailed` on failure |
| `job(job_id)` / `jobs()` | One job / all your jobs |
| `result(job_id, "txt" or "srt")` | The finished transcription, decrypted |
| `words(job_id)` | Per-word timings as a JSON string, `""` if none |
| `delete(job_id)` | Delete a job and its files |
| `set_encryption_password(pw)` | Turn on encryption (see below) |
| `verify_encryption_password(pw)` | `True` if the password opens your key |

## Things to get right

**Language is a full name, not a code.** Use `"Swedish"`, `"English"`, … (see
`scribe_api.LANGUAGES`). `start()` raises `ValueError` for anything else. This is
enforced because the worker cannot report an unknown language: it fails before
it can mark the job failed, and the job then stays `in_progress` forever.

**Output format.** `start()` takes `"TXT"` or `"SRT"`; `result()` takes `"txt"`
or `"srt"`. The client converts the case either way, so use whichever you like.
The worker produces subtitles for every job, so `result(job_id, "srt")` works
whichever format you started with. For `TXT` jobs, `result(job_id, "txt")` is
the diarized transcript as a JSON string of speaker segments.

**Encryption password.** File names and results are encrypted to your key.
Without the password the API returns ciphertext, not an error. Set
`encryption_password` on the client (or `SCRIBE_ENCRYPTION_PASSWORD`) and
`jobs()`, `job()` and `result()` decrypt for you.

**Setting the password is a one-way step.** `set_encryption_password()` makes a
new key pair protected by the password. The password cannot be recovered, and
setting a new one replaces the key pair, making everything encrypted with the
old one unreadable. The client refuses if one is already set.

**Quota.** `start()` raises `QuotaExceeded` when your quota is used up.

## Errors

All inherit from `ScribeError`, which has a `.status` (HTTP status, if any).

| Exception | When |
|---|---|
| `AuthError` | Token could not be fetched, or the API answered 401 |
| `NotFound` | Job does not exist, or is not yours |
| `QuotaExceeded` | `start()` got 403 |
| `JobFailed` | `transcribe()` ended `failed`; `.job` holds the job, including `error` |
| `RateLimited` | Still 429 after the retries |
| `ScribeError` | Anything else, including network errors |

```python
from scribe_api import ScribeClient, JobFailed, QuotaExceeded, ScribeError

try:
    job = scribe.transcribe("meeting.mp3")
except QuotaExceeded:
    ...
except JobFailed as e:
    print(e.job["error"])
except ScribeError as e:
    print(e, e.status)
```

## Example: transcribe a folder

```python
from pathlib import Path
from scribe_api import ScribeClient, ScribeError

with ScribeClient.from_env() as scribe:
    for path in sorted(Path("recordings").glob("*.mp3")):
        try:
            job = scribe.transcribe(str(path), language="English", output_format="SRT")
            path.with_suffix(".srt").write_text(scribe.result(job["uuid"], "srt"))
        except ScribeError as e:
            print(f"{path.name}: {e}")
```

## Stuck jobs

A job that stays `in_progress` has usually been picked up by a worker that then
died, or hit an unknown language (see above). Delete it with `delete(job_id)`
and submit again.

## Tests

```bash
uv run pytest
```

They run against a pretend server, so no network or credentials are needed.
