import json
from datetime import UTC, datetime
from pathlib import Path

import httpx2
import pytest

from anubis.checks import Finding, Kind
from anubis.cluster import Findings
from anubis.request_files import RequestFiles
from anubis.thoth import App, Thoth, status_since
from anubis.tokens import ASSERTION, login

APP_ID = "7d0c1f5e-0b7a-4c55-9a51-2f3c6f0f8a11"


def client(handler, base_url="http://x") -> httpx2.Client:
    return httpx2.Client(transport=httpx2.MockTransport(handler), base_url=base_url)


def app(status="retained", first_seen="2026-10-01T00:00:00Z") -> App:
    return App.model_validate_json(
        json.dumps({"id": APP_ID, "key": "golem", "status": status, "first_seen": first_seen})
    )


def test_login_sends_the_pod_token_as_the_assertion(tmp_path: Path):
    (tmp_path / "token").write_text("pod-jwt\n")
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(dict(httpx2.QueryParams(request.content.decode())))
        return httpx2.Response(200, json={"access_token": "thoth-jwt", "expires_in": 600})

    with client(handler) as http:
        token = login(http, "http://x/token/", "thoth", tmp_path / "token")
    assert token.get_secret_value() == "thoth-jwt"
    assert seen["client_assertion"] == "pod-jwt"
    assert seen["client_assertion_type"] == ASSERTION
    assert seen["scope"] == "thoth"


def test_apps_asks_thoth_for_one_status():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/items"
        assert request.url.params["type"] == "app"
        assert request.url.params["status"] == "planned"
        return httpx2.Response(200, json=[{"id": APP_ID, "key": "golem", "status": "planned", "name": "golem"}])

    with client(handler) as http:
        assert [a.key for a in Thoth(http=http).apps("planned")] == ["golem"]


def test_since_walks_the_history_back_to_the_status_change():
    history = [
        {"status": "retained", "valid_from": "2026-11-04T10:00:00Z"},  # an attribute change, same status
        {"status": "retained", "valid_from": "2026-11-03T22:20:00Z"},  # entered retained
        {"status": "decommissioning", "valid_from": "2026-11-03T22:16:00Z"},
        {"status": "retained", "valid_from": "2026-10-01T00:00:00Z"},  # an earlier round, not this one
    ]
    with client(lambda _: httpx2.Response(200, json=history)) as http:
        assert Thoth(http=http).since(app()) == datetime(2026, 11, 3, 22, 20, tzinfo=UTC)


def test_since_falls_back_to_first_seen():
    assert status_since(app(), []) == datetime(2026, 10, 1, tzinfo=UTC)


def test_a_missing_request_file_is_none():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/api/v1/repos/Meru/requests/raw/apps/golem.yaml"
        return httpx2.Response(404)

    with client(handler) as http:
        assert RequestFiles(http=http, repo="Meru/requests").read("golem") is None


def test_a_request_file_is_read():
    body = "metadata:\n  name: golem\n  removedAt: 2026-11-03T22:15:36Z\nspec:\n  removed: true\n  owner: mario\n"
    with client(lambda _: httpx2.Response(200, text=body)) as http:
        request = RequestFiles(http=http, repo="Meru/requests").read("golem")
    assert request is not None
    assert request.spec.removed
    assert request.metadata.removed_at == datetime(2026, 11, 3, 22, 15, 36, tzinfo=UTC)


FINDING = Finding(app="golem", kind=Kind.PURGE, since=None, detail="d")
NOW = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("exists", [True, False])
def test_findings_patch_or_create(exists: bool):
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, request.url.path))
        if request.method == "PATCH" and not exists:
            return httpx2.Response(404)
        body = json.loads(request.content)
        assert json.loads(body["data"]["findings.json"])[0]["kind"] == "purge-overdue"
        assert body["data"]["checked-at"] == "2026-12-10T12:00:00+00:00"
        return httpx2.Response(200 if request.method == "PATCH" else 201)

    with client(handler) as http:
        Findings(http=http, namespace="anubis", name="anubis-findings").write([FINDING], NOW)
    patch = ("PATCH", "/api/v1/namespaces/anubis/configmaps/anubis-findings")
    assert calls == ([patch] if exists else [patch, ("POST", "/api/v1/namespaces/anubis/configmaps")])


def test_findings_refused_raises():
    with client(lambda _: httpx2.Response(403)) as http, pytest.raises(httpx2.HTTPStatusError):
        Findings(http=http, namespace="anubis", name="anubis-findings").write([], NOW)
