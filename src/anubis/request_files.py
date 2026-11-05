"""An app's request on Meru/requests' main, only the fields that date a retired app (D116): removedAt + retention.

Read loosely on purpose, as Charon does: Shikigami's gate has already checked the files, and a new field must not stop
a pass.
"""

from datetime import timedelta
from typing import Annotated

import httpx2
import yaml
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

from anubis.incoming import Incoming

Days = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,3}d$")]


class _Metadata(Incoming):
    name: str
    removed_at: AwareDatetime | None = Field(default=None, alias="removedAt")


class _Spec(Incoming):
    removed: bool = False
    retention: Days = "30d"  # the same default as the request format


class AppRequest(Incoming):
    """One app's request file."""

    metadata: _Metadata
    spec: _Spec

    @property
    def retention(self) -> timedelta:
        """How long after its removal the app is kept."""
        return timedelta(days=int(self.spec.retention.removesuffix("d")))


class RequestFiles(BaseModel):
    """Meru/requests on Gitea, with a token that can only read that repo."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    http: httpx2.Client
    repo: str

    def read(self, app: str) -> AppRequest | None:
        """The app's request, or None when there is no file (Charon deleted it, or it never existed)."""
        response = self.http.get(f"/api/v1/repos/{self.repo}/raw/apps/{app}.yaml")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return AppRequest.model_validate(yaml.safe_load(response.text))
