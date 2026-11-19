"""Tests for the api/ client, against a pretend Scribe on a requests adapter."""

import base64
import json
import time

import pytest
import requests
from requests.adapters import BaseAdapter

from scribe import (
    AuthError,
    JobFailed,
    NotFound,
    QuotaExceeded,
    RateLimited,
    ScribeClient,
    ScribeError,
    Throttle,
    Token,
)


class FakeScribe(BaseAdapter):
    """Answers by (method, path); records every request."""

    def __init__(self, routes):
        super().__init__()
        self.routes = routes
        self.calls = []

    def send(self, request, **kwargs):
        path = request.path_url.split("?")[0].removeprefix("/api/v1")
        is_json = request.headers.get("Content-Type", "").startswith(
            "application/json"
        )
        body = json.loads(request.body) if request.body and is_json else None
        self.calls.append((request.method, path, body, request.headers))

        handler = self.routes[(request.method, path)]
        answer = handler(len(self.calls)) if callable(handler) else handler
        status, payload, *extra = answer

        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        response.headers.update(extra[0] if extra else {})
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


def make(routes, **kwargs):
    client = ScribeClient("tok", base_url="http://scribe/api/v1", **kwargs)
    adapter = FakeScribe(routes)
    client._session.mount("http://", adapter)
    return client, adapter


JOB = {"uuid": "j1", "status": "completed"}


def test_check_sends_bearer():
    client, fake = make({("GET", "/me"): (200, {"result": {"user_id": "u"}})})
    assert client.check() == {"user_id": "u"}
    assert fake.calls[0][3]["Authorization"] == "Bearer tok"


def test_bad_token_is_a_scribe_error():
    client, _ = make({("GET", "/me"): (401, {"detail": "no"})})
    with pytest.raises(ScribeError) as e:
        client.check()
    assert e.value.status == 401


def test_401_refreshes_token_once():
    tokens = iter(["old", "new"])
    seen = []

    def handler(n):
        return (401, {}) if n == 1 else (200, {"result": {}})

    client = ScribeClient(lambda: next(tokens), base_url="http://scribe/api/v1")
    fake = FakeScribe({("GET", "/me"): handler})
    client._session.mount("http://", fake)
    client.me()
    seen = [c[3]["Authorization"] for c in fake.calls]
    assert seen == ["Bearer old", "Bearer new"]


def _counting_source(lifetime):
    """Token source that counts fetches; tokens live ``lifetime`` seconds on
    the monotonic clock the test controls."""
    import time

    fetched = []

    def source():
        fetched.append(1)
        return Token(f"t{len(fetched)}", time.monotonic() + lifetime)

    return source, fetched


def test_valid_token_is_fetched_once_and_reused():
    source, fetched = _counting_source(3600)
    client = ScribeClient(source, base_url="http://scribe/api/v1")
    client._session.mount(
        "http://", FakeScribe({("GET", "/me"): (200, {"result": {}})})
    )
    client.me()
    client.me()
    client.me()
    assert len(fetched) == 1


def test_expired_token_is_refetched(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("scribe.auth.time.monotonic", lambda: now[0])
    source, fetched = _counting_source(0)
    # Lifetime 0 on the fake clock: expired the moment it is checked.
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    client = ScribeClient(source, base_url="http://scribe/api/v1")
    fake = FakeScribe({("GET", "/me"): (200, {"result": {}})})
    client._session.mount("http://", fake)
    client.me()
    now[0] += 1
    client.me()
    assert [c[3]["Authorization"] for c in fake.calls] == ["Bearer t1", "Bearer t2"]


def test_token_inside_leeway_counts_as_expired(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("scribe.auth.time.monotonic", lambda: now[0])
    monkeypatch.setattr("time.monotonic", lambda: now[0])
    source, fetched = _counting_source(ScribeClient.TOKEN_LEEWAY - 1)
    client = ScribeClient(source, base_url="http://scribe/api/v1")
    client._session.mount(
        "http://", FakeScribe({("GET", "/me"): (200, {"result": {}})})
    )
    client.me()
    client.me()
    assert len(fetched) == 2


def test_401_on_unexpired_token_is_not_retried():
    source, fetched = _counting_source(3600)
    client = ScribeClient(source, base_url="http://scribe/api/v1")
    fake = FakeScribe({("GET", "/me"): (401, {"detail": "no"})})
    client._session.mount("http://", fake)
    with pytest.raises(AuthError):
        client.me()
    assert len(fetched) == 1
    assert len(fake.calls) == 1


def test_static_token_is_never_refreshed():
    client, fake = make({("GET", "/me"): (401, {})})
    with pytest.raises(AuthError):
        client.me()
    assert len(fake.calls) == 1


def test_start_rejects_unknown_language_before_sending():
    client, fake = make({})
    for bad in ("xx", "Klingon", ""):
        with pytest.raises(ValueError):
            client.start("j1", language=bad)
    assert fake.calls == []


@pytest.mark.parametrize(
    "given, sent",
    [
        ("sv", "Swedish"),
        ("SV", "Swedish"),
        ("en", "English"),
        ("nb", "Norwegian"),
        ("swedish", "Swedish"),
        ("Swedish", "Swedish"),
    ],
)
def test_start_sends_the_full_language_name(given, sent):
    client, fake = make(
        {("PUT", "/transcriber/j1"): (200, {"result": {"status": "pending"}})}
    )
    client.start("j1", language=given)
    assert fake.calls[0][2]["language"] == sent


def test_every_language_has_an_iso_code():
    from scribe import LANGUAGE_CODES, LANGUAGES

    assert set(LANGUAGE_CODES.values()) == set(LANGUAGES)


def test_start_uppercases_format_and_sends_password():
    client, fake = make(
        {("PUT", "/transcriber/j1"): (200, {"result": {"status": "pending"}})},
        encryption_password="pw",
    )
    client.start("j1", language="English", output_format="srt")
    body = fake.calls[0][2]
    assert body["output_format"] == "SRT"
    assert body["language"] == "English"
    assert body["encryption_password"] == "pw"


def test_start_quota_exceeded():
    client, _ = make({("PUT", "/transcriber/j1"): (403, {"result": {"error": "q"}})})
    with pytest.raises(QuotaExceeded):
        client.start("j1")


def test_job_not_found():
    client, _ = make({("GET", "/transcriber"): (200, {"result": {}})})
    with pytest.raises(NotFound):
        client.job("nope")


def test_result_lowercases_format_and_needs_password():
    client, fake = make(
        {("GET", "/transcriber/j1/result/srt"): (200, {"result": "1\n00:00"})}
    )
    with pytest.raises(ScribeError):
        client.result("j1", "SRT")
    assert client.result("j1", "SRT", password="pw") == "1\n00:00"
    assert fake.calls[0][2] == {"encryption_password": "pw"}


def test_wait_returns_when_finished(monkeypatch):
    monkeypatch.setattr("scribe.client.time.sleep", lambda s: None)
    states = iter(["pending", "in_progress", "completed"])
    client, _ = make(
        {
            ("GET", "/transcriber"): lambda n: (
                200,
                {"result": {"uuid": "j1", "status": next(states)}},
            )
        }
    )
    assert client.wait("j1")["status"] == "completed"


def test_transcribe_raises_job_failed(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.client.time.sleep", lambda s: None)
    media = tmp_path / "a.mp3"
    media.write_bytes(b"x")
    client, _ = make(
        {
            ("POST", "/transcriber"): (200, {"result": {"uuid": "j1"}}),
            ("PUT", "/transcriber/j1"): (200, {"result": {}}),
            ("GET", "/transcriber"): (
                200,
                {"result": {"uuid": "j1", "status": "failed", "error": "boom"}},
            ),
        }
    )
    with pytest.raises(JobFailed) as e:
        client.transcribe(str(media))
    assert e.value.job["error"] == "boom"


def test_set_password_refuses_to_replace_existing_key():
    client, fake = make(
        {("GET", "/me"): (200, {"result": {"encryption_settings": True}})}
    )
    with pytest.raises(ScribeError):
        client.set_encryption_password("pw")
    assert [c[0] for c in fake.calls] == ["GET"]


# -- throttling ------------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_throttle_allows_a_burst_then_spaces_requests():
    clock = FakeClock()
    throttle = Throttle(rate=2, burst=3, clock=clock, sleep=clock.sleep)
    waits = [throttle.acquire() for _ in range(5)]
    assert waits[:3] == [0, 0, 0]
    # Out of tokens: one request per half second from here on.
    assert waits[3] == pytest.approx(0.5)
    assert waits[4] == pytest.approx(0.5)


def test_throttle_gives_concurrent_callers_successive_slots():
    clock = FakeClock()
    slept = []
    throttle = Throttle(rate=2, burst=1, clock=clock, sleep=slept.append)
    # The clock does not move (the sleeps are not served), as when several
    # threads arrive together: each is told to wait for its own slot.
    assert [throttle.acquire() for _ in range(4)] == [0, 0.5, 1.0, 1.5]


def test_throttle_refills_while_idle():
    clock = FakeClock()
    throttle = Throttle(rate=1, burst=1, clock=clock, sleep=clock.sleep)
    throttle.acquire()
    clock.now += 5
    assert throttle.acquire() == 0


def test_throttle_rejects_bad_settings():
    with pytest.raises(ValueError):
        Throttle(rate=0)
    with pytest.raises(ValueError):
        Throttle(rate=5, burst=0)


def test_client_throttles_every_request(monkeypatch):
    clock = FakeClock()
    client, _ = make({("GET", "/me"): (200, {"result": {}})})
    client._throttle = Throttle(rate=1, burst=1, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        client.me()
    assert clock.slept == [pytest.approx(1.0), pytest.approx(1.0)]


def test_throttling_can_be_turned_off():
    client, _ = make({}, requests_per_second=None)
    assert client._throttle is None


def test_429_is_retried_after_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr("scribe.client.time.sleep", slept.append)
    client, fake = make(
        {
            ("GET", "/me"): lambda n: (
                (429, {}, {"Retry-After": "7"}) if n == 1 else (200, {"result": {}})
            )
        }
    )
    client.me()
    assert slept == [7.0]
    assert len(fake.calls) == 2


def test_429_without_header_backs_off_exponentially(monkeypatch):
    slept = []
    monkeypatch.setattr("scribe.client.time.sleep", slept.append)
    client, _ = make(
        {
            ("GET", "/me"): lambda n: (
                (429, {}) if n <= 3 else (200, {"result": {}})
            )
        }
    )
    client.me()
    assert slept == [1.0, 2.0, 4.0]


def test_retry_after_is_capped(monkeypatch):
    slept = []
    monkeypatch.setattr("scribe.client.time.sleep", slept.append)
    client, _ = make(
        {
            ("GET", "/me"): lambda n: (
                (429, {}, {"Retry-After": "99999"})
                if n == 1
                else (200, {"result": {}})
            )
        }
    )
    client.me()
    assert slept == [ScribeClient.MAX_RETRY_WAIT]


def test_429_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("scribe.client.time.sleep", lambda s: None)
    client, fake = make({("GET", "/me"): (429, {})}, max_retries=2)
    with pytest.raises(RateLimited) as e:
        client.me()
    assert e.value.status == 429
    assert len(fake.calls) == 3  # first try + 2 retries


def test_wait_never_polls_faster_than_the_minimum(monkeypatch):
    slept = []
    monkeypatch.setattr("scribe.client.time.sleep", slept.append)
    states = iter(["pending", "completed"])
    client, _ = make(
        {
            ("GET", "/transcriber"): lambda n: (
                200,
                {"result": {"uuid": "j1", "status": next(states)}},
            )
        }
    )
    client.wait("j1", poll_seconds=0)
    assert slept == [ScribeClient.MIN_POLL_SECONDS]


def _jwt(exp):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'none'})}.{enc({'exp': exp})}.sig"


def test_jwt_expiry_is_read():
    t = Token.from_jwt(_jwt(time.time() + 3600))
    assert not t.expired() and t.expires_at is not None
    assert Token.from_jwt("not-a-jwt").expires_at is None


def test_expired_jwt_raises_before_request():
    client, fake = make({("GET", "/me"): (200, {})})
    client._token = Token.from_jwt(_jwt(time.time() - 10))
    with pytest.raises(AuthError):
        client.check()
    assert not fake.calls


def test_from_env_uses_jwt(monkeypatch):
    for k in ("OIDC_TOKEN_ENDPOINT", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    jwt = _jwt(time.time() + 3600)
    monkeypatch.setenv("SCRIBE_JWT", jwt)
    assert ScribeClient.from_env()._bearer() == {"Authorization": f"Bearer {jwt}"}
