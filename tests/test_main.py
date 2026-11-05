from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from anubis import __main__ as anubis
from anubis.checks import Kind, Limits
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


def thoth_handler(request: httpx2.Request) -> httpx2.Response:
    if request.url.path == "/v1/items":
        return httpx2.Response(200, json=ITEMS[request.url.params["status"]])
    n = request.url.path.split("/")[3][-1]
    status = next(item["status"] for items in ITEMS.values() for item in items if item["id"].endswith(n))
    return httpx2.Response(200, json=[{"status": status, "valid_from": SINCE[n]}])


def gitea_handler(_: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(
        200, text="metadata:\n  name: golem\n  removedAt: 2026-11-03T22:15:36Z\nspec:\n  removed: true\n"
    )


def test_weigh_reports_only_what_is_stuck_in_a_stable_order():
    with (
        httpx2.Client(transport=httpx2.MockTransport(thoth_handler), base_url="http://thoth") as thoth,
        httpx2.Client(transport=httpx2.MockTransport(gitea_handler), base_url="http://gitea") as gitea,
    ):
        findings = anubis.weigh(Thoth(http=thoth), RequestFiles(http=gitea, repo="Meru/requests"), NOW, LIMITS)
    # fresh is planned for an hour: fine. kitsune decommissioning 9 days, golem 37 days past removal.
    assert [(f.kind, f.app) for f in findings] == [(Kind.PURGE, "golem"), (Kind.RETIRE, "kitsune")]


@pytest.mark.parametrize("code", [0, 1])
def test_main_exits_with_the_pass_result(monkeypatch: pytest.MonkeyPatch, code: int):
    monkeypatch.setattr(anubis, "run", lambda: code)
    with pytest.raises(SystemExit) as exited:
        anubis.main()
    assert exited.value.code == code
