"""What Anubis reads from Thoth and tells it: apps in a status and since when, the unseen queue, and verdicts.

Reads need thoth.read, verdicts thoth.verdict (D118). `changed_at` moves on any change to the row, not only the
status, so "stuck since" comes from the item's history: the oldest version in the unbroken run of the current status.
"""

from datetime import datetime
from uuid import UUID

import httpx2
from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter

from anubis.clients.incoming import Incoming


class App(Incoming):
    """An app item, only the fields Anubis decides on."""

    id: UUID
    key: str
    status: str
    first_seen: AwareDatetime | None = None


class _Version(Incoming):
    status: str
    valid_from: AwareDatetime | None = None


def status_since(app: App, versions: list[_Version]) -> datetime | None:
    """When the app entered its current status: versions come newest first, the current one included."""
    since = None
    for version in versions:
        if version.status != app.status:
            break
        since = version.valid_from
    return since or app.first_seen


class Item(Incoming):
    """An item on the unseen queue."""

    type: str
    key: str
    status: str


class Unseen(Incoming):
    """One source + scope that stopped seeing an item (Thoth GET /v1/unseen)."""

    item: Item
    source: str
    scope: str
    missed_scans: int


_APPS = TypeAdapter(list[App])
_UNSEEN = TypeAdapter(list[Unseen])
_VERSIONS = TypeAdapter(list[_Version])


class Thoth(BaseModel):
    """Thoth's API, with a read-only token."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    http: httpx2.Client

    def apps(self, status: str) -> list[App]:
        """Every app in this status (a home lab has far fewer than one page)."""
        response = self.http.get("/v1/items", params={"type": "app", "status": status, "limit": 1000})
        response.raise_for_status()
        return _APPS.validate_json(response.content)

    def since(self, app: App) -> datetime | None:
        """When the app entered its current status."""
        response = self.http.get(f"/v1/items/{app.id}/history")
        response.raise_for_status()
        return status_since(app, _VERSIONS.validate_json(response.content))

    def unseen(self) -> list[Unseen]:
        """What scanners stopped seeing long enough for a direct check."""
        response = self.http.get("/v1/unseen")
        response.raise_for_status()
        return _UNSEEN.validate_json(response.content)

    def verdict(self, item: Item, status: str, reason: str) -> None:
        """Give a verdict - missing or retired. One already given is answered as it is."""
        response = self.http.post(
            "/v1/verdicts", json={"type": item.type, "key": item.key, "status": status, "reason": reason}
        )
        response.raise_for_status()
