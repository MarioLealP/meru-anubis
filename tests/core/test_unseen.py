import httpx2
import pytest

from anubis.clients.lookups import Look, Lookups, Seen
from anubis.clients.thoth import Item
from anubis.core.checks import Kind
from anubis.core.unseen import judge, label

WORKLOAD = Item(type="workload", key="clockmost/charon/deployment/charon", status="active")
APP = Item(type="app", key="golem", status="active")


def look(seen: Seen) -> Look:
    return Look(seen=seen, how="get x answered y")


def test_still_there_is_a_scanner_blind_spot_not_a_verdict():
    decision = judge(WORKLOAD, ["k8s-scan"], look(Seen.PRESENT), declared=False)
    assert decision.verdict is None
    assert decision.finding is not None
    assert (decision.finding.kind, decision.finding.app) == (Kind.SCANNER_LOST, "workload:" + WORKLOAD.key)
    assert "k8s-scan lost it" in decision.finding.detail


def test_cant_tell_changes_nothing():
    decision = judge(WORKLOAD, ["k8s-scan"], look(Seen.UNKNOWN), declared=False)
    assert decision.verdict is None
    assert decision.finding is not None
    assert decision.finding.kind == Kind.UNCHECKED


def test_gone_and_declared_is_missing_with_a_problem():
    decision = judge(APP, ["k8s-scan"], look(Seen.GONE), declared=True)
    assert decision.verdict == "missing"
    assert decision.finding is not None
    assert (decision.finding.kind, decision.finding.app) == (Kind.MISSING, "golem")


def test_gone_and_undeclared_is_retired_quietly():
    decision = judge(WORKLOAD, ["k8s-scan", "k8s-scan"], look(Seen.GONE), declared=False)
    assert (decision.verdict, decision.finding) == ("retired", None)
    assert decision.reason == "unseen by k8s-scan; gone: get x answered y"  # each scanner named once


def test_label_names_apps_plainly_and_others_by_type():
    assert (label(APP), label(WORKLOAD)) == ("golem", "workload:clockmost/charon/deployment/charon")


def lookups(handler) -> Lookups:
    return Lookups(http=httpx2.Client(transport=httpx2.MockTransport(handler), base_url="http://k8s"))


@pytest.mark.parametrize(
    ("key", "path"),
    [
        ("clockmost/charon/deployment/charon", "/apis/apps/v1/namespaces/charon/deployments/charon"),
        ("clockmost/thoth/statefulset/db", "/apis/apps/v1/namespaces/thoth/statefulsets/db"),
        ("clockmost/falco/daemonset/falco", "/apis/apps/v1/namespaces/falco/daemonsets/falco"),
        ("clockmost/anubis/cronjob/anubis", "/apis/batch/v1/namespaces/anubis/cronjobs/anubis"),
    ],
)
def test_a_workload_is_got_by_name(key: str, path: str):
    asked = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        asked.append(request.url.path)
        return httpx2.Response(404)

    assert lookups(handler).look("workload", key).seen == Seen.GONE
    assert asked == [path]


def test_an_app_is_its_argo_application():
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/app-golem"
        return httpx2.Response(200, json={"status": {"health": {"status": "Degraded"}}})

    assert lookups(handler).look("app", "golem").seen == Seen.PRESENT  # broken is not gone


@pytest.mark.parametrize("code", [401, 403, 500])
def test_any_other_answer_is_cant_tell(code: int):
    look = lookups(lambda _: httpx2.Response(code)).look("app", "golem")
    assert (look.seen, look.how) == (
        Seen.UNKNOWN,
        f"get /apis/argoproj.io/v1alpha1/namespaces/argocd/applications/app-golem answered {code}",
    )


def test_a_failed_request_is_cant_tell():
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    assert lookups(handler).look("app", "golem").seen == Seen.UNKNOWN


@pytest.mark.parametrize(
    ("item_type", "key"),
    [
        ("host", "clockmost-desktop"),  # no check for this type yet
        ("workload", "nitro5/ai/deployment/llm"),  # another cluster
        ("workload", "clockmost/ai/pod/llm"),  # a kind Heimdall doesn't report
        ("workload", "clockmost/broken"),
    ],
)
def test_no_check_is_cant_tell(item_type: str, key: str):
    def handler(_: httpx2.Request) -> httpx2.Response:
        raise AssertionError("nothing should be asked")

    assert lookups(handler).look(item_type, key).seen == Seen.UNKNOWN
