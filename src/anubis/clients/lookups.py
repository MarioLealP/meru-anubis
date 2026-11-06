"""Anubis's direct checks (D118): is something scanners stopped seeing really gone? Asked by another path than theirs.

- A workload (`<cluster>/<namespace>/<kind>/<name>`, Heimdall's key): `get` that exact object by name - Heimdall lists
  by kind, so a filter bug there doesn't repeat here.
- An app: its Argo Application `app-<name>`. There = present whatever its health - a crashing app is broken, not
  gone, and that is another alert. Heimdall looks at namespaces and pods instead.

Rights (Meru/meru rbac/anubis-checks.yaml): get on those four kinds cluster-wide, get on Applications in argocd. Any
answer but 200 or 404 - or a type with no check yet - is "can't tell", and nothing changes.
"""

from enum import StrEnum

import httpx2
from pydantic import BaseModel, ConfigDict

PATHS = {
    "deployment": "/apis/apps/v1/namespaces/{ns}/deployments/{name}",
    "statefulset": "/apis/apps/v1/namespaces/{ns}/statefulsets/{name}",
    "daemonset": "/apis/apps/v1/namespaces/{ns}/daemonsets/{name}",
    "cronjob": "/apis/batch/v1/namespaces/{ns}/cronjobs/{name}",
}


class Seen(StrEnum):
    """What a direct check found."""

    PRESENT = "present"
    GONE = "gone"
    UNKNOWN = "unknown"


class Look(BaseModel):
    """A direct check's answer and how it was asked, for the verdict's reason."""

    model_config = ConfigDict(frozen=True)

    seen: Seen
    how: str


class Lookups(BaseModel):
    """The Kubernetes API, with the pod's own token."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    http: httpx2.Client
    cluster: str = "clockmost"
    argocd_namespace: str = "argocd"

    def look(self, item_type: str, key: str) -> Look:
        """Check one item directly."""
        if item_type == "app":
            return self._get(f"/apis/argoproj.io/v1alpha1/namespaces/{self.argocd_namespace}/applications/app-{key}")
        if item_type == "workload":
            cluster, _, rest = key.partition("/")
            parts = rest.split("/")
            if cluster == self.cluster and len(parts) == 3 and parts[1] in PATHS:
                ns, kind, name = parts
                return self._get(PATHS[kind].format(ns=ns, name=name))
        return Look(seen=Seen.UNKNOWN, how=f"no direct check for {item_type} {key} yet")

    def _get(self, path: str) -> Look:
        try:
            response = self.http.get(path)
        except httpx2.HTTPError as e:
            return Look(seen=Seen.UNKNOWN, how=f"get {path} failed: {type(e).__name__}")
        how = f"get {path} answered {response.status_code}"
        if response.status_code == 200:
            return Look(seen=Seen.PRESENT, how=how)
        if response.status_code == 404:
            return Look(seen=Seen.GONE, how=how)
        return Look(seen=Seen.UNKNOWN, how=how)
