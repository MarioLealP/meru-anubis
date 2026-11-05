import json
from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from anubis import __main__ as anubis
from anubis.checks import Kind, Limits
from anubis.lookups import Lookups
from anubis.request_files import RequestFiles
from anubis.thoth import Thoth

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
LIMITS = Limits(stuck_after=timedelta(days=1), purge_grace=timedelta(days=1))
ITEMS = {
    "planned": [{"id": "00000000-0000-0000-0000-000000000001", "key": "fresh", "status": "planned"}],
    "decommissioning": [{"id": "00000000-0000-0000-0000-000000000002", "key": "kitsune", "status": "decommissioning"}],
    "retained": [{"id": "00000000-0000-0000-0000-000000000003", "key": "golem", "status": "retained"}],
}
SINCE = {"1": "2026-12-10T11:00:00Z", "2": "2026-12-01T00:00:00Z", "3": "2026-11-03T22:20:00Z"}
OLD_DEPLOYMENT = "clockmost/charon/deployment/charon"


def unseen(item_type: str, key: str, status: str = "active", scope: str = "clockmost") -> dict:
    return {"item": {"type": item_type, "key": key, "status": status}, "source": "k8s-scan", "scope": scope,
            "missed_scans": 3}  # fmt: skip


UNSEEN = [
    unseen("workload", OLD_DEPLOYMENT),  # gone, nothing declares a workload: retired
    unseen("app", "anubis"),  # Argo has it: Heimdall's blind spot
    unseen("app", "anubis", scope="other"),  # the same item lost twice: judged once
    unseen("app", "lostapp"),  # gone, its request is live: missing
    unseen("app", "stillgone", status="missing"),  # missing already: no new verdict, still a problem
]


class FakeThoth:
    def __init__(self) -> None:
        self.verdicts: list[tuple[str, str, str]] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/items":
            return httpx2.Response(200, json=ITEMS[request.url.params["status"]])
        if request.url.path == "/v1/unseen":
            return httpx2.Response(200, json=UNSEEN)
        if request.url.path == "/v1/verdicts":
            body = json.loads(request.content)
            self.verdicts.append((body["type"], body["key"], body["status"]))
            return httpx2.Response(200, json={})
        n = request.url.path.split("/")[3][-1]
        status = next(item["status"] for items in ITEMS.values() for item in items if item["id"].endswith(n))
        return httpx2.Response(200, json=[{"status": status, "valid_from": SINCE[n]}])


REQUESTS = {
    "golem": "metadata:\n  name: golem\n  removedAt: 2026-11-03T22:15:36Z\nspec:\n  removed: true\n",
    "lostapp": "metadata:\n  name: lostapp\nspec:\n  owner: mario\n",
    "stillgone": "metadata:\n  name: stillgone\nspec:\n  owner: mario\n",
}


def gitea_handler(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/api/v1/repos/Meru/requests":
        return httpx2.Response(200, json={})
    name = request.url.path.rsplit("/", 1)[1].removesuffix(".yaml")
    return httpx2.Response(200, text=REQUESTS[name]) if name in REQUESTS else httpx2.Response(404)


def kubernetes_handler(request: httpx2.Request) -> httpx2.Response:
    present = {"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/app-anubis"}
    return httpx2.Response(200, json={}) if request.url.path in present else httpx2.Response(404)


def weigh(gitea=gitea_handler, *, give: bool = True) -> tuple[list, FakeThoth]:
    fake = FakeThoth()
    with (
        httpx2.Client(transport=httpx2.MockTransport(fake), base_url="http://thoth") as thoth,
        httpx2.Client(transport=httpx2.MockTransport(gitea), base_url="http://gitea") as git,
        httpx2.Client(transport=httpx2.MockTransport(kubernetes_handler), base_url="http://k8s") as k8s,
    ):
        findings = anubis.weigh(
            Thoth(http=thoth), RequestFiles(http=git, repo="Meru/requests"), Lookups(http=k8s), NOW, LIMITS, give=give
        )
    return findings, fake


def test_a_pass_reports_stuck_and_unseen_in_a_stable_order():
    findings, _ = weigh()
    # fresh is planned for an hour: fine. kitsune decommissioning 9 days, golem 37 days past removal.
    assert [(f.kind, f.app) for f in findings] == [
        (Kind.MISSING, "lostapp"),
        (Kind.MISSING, "stillgone"),
        (Kind.PURGE, "golem"),
        (Kind.RETIRE, "kitsune"),
        (Kind.SCANNER_LOST, "anubis"),
    ]


def test_a_pass_gives_only_the_verdicts_that_change_something():
    _, fake = weigh()
    assert fake.verdicts == [("workload", OLD_DEPLOYMENT, "retired"), ("app", "lostapp", "missing")]


def test_switched_off_it_gives_no_verdicts_but_reports_the_same(caplog: pytest.LogCaptureFixture):
    caplog.set_level("INFO", logger="anubis")
    findings, fake = weigh(give=False)
    assert fake.verdicts == []
    assert len(findings) == 5
    assert f"would be retired workload {OLD_DEPLOYMENT}" in caplog.text


def test_weigh_fails_when_the_requests_repo_is_hidden():
    def hidden(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404 if request.url.path == "/api/v1/repos/Meru/requests" else 200, text="")

    with pytest.raises(httpx2.HTTPStatusError):
        weigh(gitea=hidden)


@pytest.mark.parametrize("code", [0, 1])
def test_main_exits_with_the_pass_result(monkeypatch: pytest.MonkeyPatch, code: int):
    monkeypatch.setattr(anubis, "run", lambda: code)
    with pytest.raises(SystemExit) as exited:
        anubis.main()
    assert exited.value.code == code
