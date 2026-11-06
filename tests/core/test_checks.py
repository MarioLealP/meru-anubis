from datetime import UTC, datetime, timedelta

import pytest

from anubis.clients.request_files import AppRequest
from anubis.core.checks import Kind, Limits, retained, stuck

NOW = datetime(2026, 12, 10, 12, 0, tzinfo=UTC)
LIMITS = Limits(stuck_after=timedelta(days=1), purge_grace=timedelta(days=1))


def request(
    removed: bool = True, removed_at: datetime | None = datetime(2026, 11, 3, 22, 15, tzinfo=UTC), retention="30d"
):
    metadata = {"name": "golem"} | ({"removedAt": removed_at} if removed_at else {})
    return AppRequest.model_validate({"metadata": metadata, "spec": {"removed": removed, "retention": retention}})


@pytest.mark.parametrize(("status", "kind"), [("planned", Kind.ONBOARDING), ("decommissioning", Kind.RETIRE)])
def test_stuck_past_a_day(status, kind):
    finding = stuck("golem", status, NOW - timedelta(days=1, seconds=1), NOW, LIMITS)
    assert finding is not None
    assert finding.kind == kind
    assert finding.app == "golem"


@pytest.mark.parametrize("status", ["planned", "decommissioning"])
def test_not_stuck_within_a_day(status):
    assert stuck("golem", status, NOW - timedelta(days=1), NOW, LIMITS) is None


def test_unknown_since_is_not_stuck():
    assert stuck("golem", "planned", None, NOW, LIMITS) is None


def test_retained_within_retention_is_fine():
    # removed 11-03 22:15 + 30 days + 1 day grace = due 12-04 22:15
    assert retained("golem", None, request(), datetime(2026, 12, 4, 22, 15, tzinfo=UTC), LIMITS) is None


def test_retained_past_retention_is_a_purge_overdue():
    finding = retained("golem", None, request(), datetime(2026, 12, 4, 22, 16, tzinfo=UTC), LIMITS)
    assert finding is not None
    assert finding.kind == Kind.PURGE
    assert "2026-12-04 22:15Z" in finding.detail


def test_retained_uses_the_requests_own_retention():
    assert retained("golem", None, request(retention="60d"), NOW, LIMITS) is None


@pytest.mark.parametrize("req", [None, request(removed=False), request(removed_at=None)])
def test_retained_without_a_dated_removal_is_undated(req):
    finding = retained("golem", None, req, NOW, LIMITS)
    assert finding is not None
    assert finding.kind == Kind.UNDATED
