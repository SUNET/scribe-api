# Scribe API client

A small Python client for the Sunet Scribe API: upload a recording, start a
transcription, wait for it, and fetch the result.

Requires Python 3.10+ and [`requests`](https://pypi.org/project/requests/).

```python
from scribe import ScribeClient

with ScribeClient.from_env() as scribe:
    scribe.check()                                         # GET /me
    job = scribe.transcribe("meeting.mp3", language="Swedish", output_format="SRT")
    print(scribe.result(job["uuid"], "srt"))
```

## Install

```bash
pip install git+https://github.com/SUNET/scribe-api   # or: pip install -e . in a checkout
```

Import it as `scribe`.

## Setup

There are four ways to authenticate. `ScribeClient.from_env()` picks the first
that applies, in this order:

| # | Way | Best for |
|---|---|---|
| 1 | [A JWT from the web interface](#1-a-jwt-from-the-web-interface) | Quick tests (lasts minutes, no renewal) |
| 2 | [A Keycloak user and password](#2-a-keycloak-user-and-password) | Local accounts without MFA |
| 3 | [OIDC client credentials](#3-oidc-client-credentials) | Unattended automation |
| 4 | [Sign in once in a browser](#4-sign-in-once-in-a-browser) | People |

Way 4 is used only when none of the `OIDC_*` variables are set. Ways 3 and 4
renew the token by themselves.

Settings that apply to every way:

| Variable | Meaning |
|---|---|
| `SCRIBE_API_URL` | Defaults to `https://scribe.sunet.se/api/v1` |
| `SCRIBE_ENCRYPTION_PASSWORD` | The user's encryption password, needed to read results |

### 1. A JWT from the web interface

Set `SCRIBE_JWT`, or pass the JWT directly. The `exp` claim is read (the
signature is not checked, the API does that), so an expired JWT raises
`AuthError("The JWT has expired")` before any request. A JWT cannot be
refreshed; get a new one from the web interface.

```python
scribe = ScribeClient.from_env()     # with SCRIBE_JWT set
scribe = ScribeClient(jwt)           # or pass it
```

### 2. A Keycloak user and password

Set `OIDC_TOKEN_ENDPOINT`, `OIDC_CLIENT_ID`, `OIDC_USERNAME` and
`OIDC_PASSWORD` (`OIDC_CLIENT_SECRET` only if the client is confidential). This
is the OIDC password grant, so the client needs "Direct access grants"
enabled, and it only works for users with a local Keycloak password, without
MFA.

```python
from scribe import ScribeClient, get_password_token

scribe = ScribeClient.from_env()     # with the variables above set
scribe = ScribeClient(
    lambda: get_password_token(endpoint, client_id, "kalle", password)
)
```

### 3. OIDC client credentials

Set `OIDC_TOKEN_ENDPOINT`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`. The
client needs "Service accounts roles" enabled.

```python
from scribe import ScribeClient, get_token

scribe = ScribeClient.from_env()     # with the variables above set
scribe = ScribeClient(
    token=lambda: get_token(endpoint, client_id, client_secret),
    base_url="https://scribe.sunet.se/api/v1",
    encryption_password="...",
)
```

`token` can be a bearer token string, a `Token`, or a function returning
either.

### 4. Sign in once in a browser

No client id or secret needed. Run:

| Command | Does |
|---|---|
| `python -m scribe login` | Shows a URL and a code; sign in in the browser (SSO and MFA work) |
| `python -m scribe whoami` | Prints the username you are signed in as |
| `python -m scribe logout` | Deletes the saved login |

With `uv`: `uv run python -m scribe login`.

**Check that the code on the Keycloak page matches the one in your terminal
before approving.** Otherwise someone could send you a link and get a login for
your account.

```python
from scribe import AuthError, ScribeClient, login

try:
    scribe = ScribeClient.from_login()   # also what from_env() does
except AuthError:                        # not signed in, or the login expired
    login(prompt=lambda url, code: print(f"Open {url} and check the code: {code}"))
    scribe = ScribeClient.from_login()

with scribe:
    print(scribe.me().get("username"))
```

`login()` with no arguments prints the URL and code itself. It raises
`AuthError` if the user says no or the code expires. `logout()` deletes the
saved login.

The API token is renewed from a saved refresh token, kept in
`~/.config/scribe/token.json` (mode 0600). It is a credential: the client warns
if others can read the file, so keep it private and run `logout` on shared
machines. Credentials are only sent to `https://` token endpoints (plain
`http://` is allowed for localhost only).

| Variable | Meaning |
|---|---|
| `SCRIBE_OIDC_ISSUER` | Realm used by `login`. Defaults to the Sunet Scribe realm |
| `SCRIBE_OIDC_CLIENT_ID` | Client used by `login`. Defaults to `automations` |
| `SCRIBE_TOKEN_FILE` | Where the login is saved |

This needs the OAuth 2.0 Device Authorization Grant enabled on the public
client `automations`.

### Token renewal

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

**Language: a full name or an ISO 639-1 code.** Use `"Swedish"` or `"sv"`,
`"English"` or `"en"`, … Case does not matter. See `scribe.LANGUAGES` for the
names and `scribe.LANGUAGE_CODES` for the codes (`"nb"` and `"nn"` also mean
Norwegian). The worker only understands the full names, so the client
translates a code before sending it. `start()` raises `ValueError` for
anything else. This is enforced because the worker cannot report an unknown
language: it fails before it can mark the job failed, and the job then stays
`in_progress` forever.

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

## Security

- **Compare the code** on the Keycloak page with the one in your terminal
  before approving a `login`. Otherwise someone could send you a link and get a
  login for your account.
- **The saved login is a credential.** The refresh token in
  `~/.config/scribe/token.json` is saved with mode 0600, and the client warns
  if other users can read it (not checked on Windows). Run `logout` on shared
  machines. The access token itself is never saved.
- **Token endpoints must be `https://`.** The client refuses to send a
  password, secret or refresh token to anything else (`http://localhost` is
  allowed for testing).
- **Known gap: the API URL is not checked.** `ScribeClient(base_url=...)` and
  `SCRIBE_API_URL` accept `http://`, which would send the bearer token in plain
  text. Use `https://`, which is the default.
- **Hidden fields.** Output meant for people (`whoami`, `check_login.py`)
  leaves out any field whose name contains `key`, `secret`, `password`,
  `token`, `salt` or `hash`, because `/me` includes your encryption keys. Your
  own code still gets everything from `me()`, so do not print it.
- **Keep secrets out of the shell history and git:** the client secret, user
  password and any private key.

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
from scribe import ScribeClient, JobFailed, QuotaExceeded, ScribeError

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
from scribe import ScribeClient, ScribeError

with ScribeClient.from_env() as scribe:
    for path in sorted(Path("recordings").glob("*.mp3")):
        try:
            job = scribe.transcribe(str(path), language="English", output_format="SRT")
            path.with_suffix(".srt").write_text(scribe.result(job["uuid"], "srt"))
        except ScribeError as e:
            print(f"{path.name}: {e}")
```

## More examples

Runnable scripts are in [`examples/`](examples/):

| Script | Does |
|---|---|
| [`transcribe.py`](examples/transcribe.py) | Transcribe one file, printing each step and the job status as it changes |
| [`transcribe_batch.py`](examples/transcribe_batch.py) | Transcribe a folder or list of files: upload all, start all, then collect each result as it finishes |

```bash
python examples/transcribe.py meeting.mp3 English srt
python examples/transcribe_batch.py recordings/ --language en --format srt
```

## Stuck jobs

A job that stays `in_progress` has usually been picked up by a worker that then
died, or hit an unknown language (see above). Delete it with `delete(job_id)`
and submit again.

## Development

```bash
uv sync          # create the venv and install the dev dependencies
uv run pytest    # run the tests
uv build         # build the sdist and wheel into dist/
```

The tests run against a pretend server, so no network or credentials are
needed.

To release, bump `version` in `pyproject.toml`, tag it (`git tag v0.1.1`) and
push the tag.
