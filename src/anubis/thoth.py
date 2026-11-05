"""What Anubis reads from Thoth: apps in a status, and since when they have been in it.

Read-only (thoth.read). `changed_at` moves on any change to the row, not only the status, so "stuck since" comes from
the item's history: the oldest version in the unbroken run of the current status.
"""

from datetime import datetime
from uuid import UUID

import httpx2
from pydantic import AwareDatetime, BaseModel, ConfigDict, TypeAdapter

from anubis.incoming import Incoming


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


_APPS = TypeAdapter(list[App])
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
