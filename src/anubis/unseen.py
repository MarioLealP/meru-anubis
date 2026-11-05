"""The verdict on something scanners stopped seeing (D53, D118) - decided from the direct check, no I/O here.

- still there: no verdict; Zabbix "<scanner> lost <item>" (the scanner has a blind spot)
- gone, and a request declares it (an app whose request isn't removed): `missing`, and a Zabbix problem
- gone, and nothing declares it: `retired` - the history keeps it; nothing to alert
- can't tell (the check failed, or no check for that type yet): nothing changes; Zabbix "unchecked"
"""

from pydantic import BaseModel, ConfigDict

from anubis.checks import Finding, Kind
from anubis.lookups import Look, Seen
from anubis.thoth import Item


class Decision(BaseModel):
    """What to do about one unseen item."""

    model_config = ConfigDict(frozen=True)

    verdict: str | None  # missing | retired | None
    reason: str
    finding: Finding | None


def label(item: Item) -> str:
    """How a finding names the item: an app by its name (as the stuck checks do), anything else as type:key."""
    return item.key if item.type == "app" else f"{item.type}:{item.key}"


def judge(item: Item, sources: list[str], look: Look, declared: bool) -> Decision:
    """The verdict and finding for one item that `sources` stopped seeing."""
    lost_by = ", ".join(sorted(set(sources)))
    if look.seen == Seen.PRESENT:
        detail = f"{lost_by} lost it, but it's there ({look.how})"
        return Decision(verdict=None, reason=detail, finding=_finding(item, Kind.SCANNER_LOST, detail))
    if look.seen == Seen.UNKNOWN:
        detail = f"unseen by {lost_by}; can't tell: {look.how}"
        return Decision(verdict=None, reason=detail, finding=_finding(item, Kind.UNCHECKED, detail))
    reason = f"unseen by {lost_by}; gone: {look.how}"
    if declared:
        return Decision(verdict="missing", reason=reason, finding=_finding(item, Kind.MISSING, reason))
    return Decision(verdict="retired", reason=reason, finding=None)


def _finding(item: Item, kind: Kind, detail: str) -> Finding:
    return Finding(app=label(item), kind=kind, since=None, detail=detail)
