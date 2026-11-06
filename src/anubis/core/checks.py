"""D85's stuck states, decided from what was read - no I/O here, so every case is a plain test.

- planned longer than a day: onboarding stuck (golem's refused push would have sat silently)
- decommissioning longer than a day: the retire pass stuck
- retained past removedAt + retention (+ a day for Charon's daily run): the purge overdue

Never on "still seen" while retained: the retention is the hold (D85, amending D53).
"""

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict

from anubis.clients.request_files import AppRequest


class Kind(StrEnum):
    """What is stuck."""

    ONBOARDING = "onboarding-stuck"
    RETIRE = "retire-stuck"
    PURGE = "purge-overdue"
    UNDATED = "retained-undated"  # retained, but no request says when it was removed: the date can't be checked
    # The unseen queue (D53, D118, unseen.py):
    SCANNER_LOST = "scanner-lost"  # a scanner stopped seeing it, but the direct check finds it
    MISSING = "missing"  # gone, and a request still declares it
    UNCHECKED = "unchecked"  # unseen, and the direct check couldn't tell


class Finding(BaseModel):
    """One stuck app or unseen item, as Zabbix shows it. `app` names it: an app by name, anything else as type:key."""

    model_config = ConfigDict(frozen=True)

    app: str
    kind: Kind
    since: AwareDatetime | None
    detail: str


class Limits(BaseModel):
    """How long each state may last."""

    model_config = ConfigDict(frozen=True)

    stuck_after: timedelta
    purge_grace: timedelta


_STUCK = {"planned": Kind.ONBOARDING, "decommissioning": Kind.RETIRE}


def stuck(app: str, status: str, since: datetime | None, now: datetime, limits: Limits) -> Finding | None:
    """A planned or decommissioning app past the limit. Unknown since = can't tell, so nothing."""
    kind = _STUCK[status]
    if since is None or now - since <= limits.stuck_after:
        return None
    return Finding(app=app, kind=kind, since=since, detail=f"{status} since {since:%Y-%m-%d %H:%M}Z")


def retained(
    app: str, since: datetime | None, request: AppRequest | None, now: datetime, limits: Limits
) -> Finding | None:
    """A retained app whose retention has run out, or that no request dates."""
    if request is None or not request.spec.removed or request.metadata.removed_at is None:
        why = "no request file" if request is None else "its request has no removed: true + removedAt"
        return Finding(app=app, kind=Kind.UNDATED, since=since, detail=f"retained, but {why}")
    due = request.metadata.removed_at + request.retention + limits.purge_grace
    if now <= due:
        return None
    return Finding(
        app=app,
        kind=Kind.PURGE,
        since=since,
        detail=f"retained, purge was due by {due:%Y-%m-%d %H:%M}Z (removed {request.metadata.removed_at:%Y-%m-%d})",
    )
