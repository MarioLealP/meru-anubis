"""Anubis's one write: its findings, into a ConfigMap in its own namespace that Zabbix reads (D115).

Its rights (Meru/meru rbac/anubis-findings.yaml): create ConfigMaps in anubis, get/update/patch only this one. Built
as if Zabbix ran in k3s: nothing here knows where Zabbix is.
"""

import json
from datetime import datetime

import httpx2
from pydantic import BaseModel, ConfigDict, TypeAdapter

from anubis.checks import Finding

_FINDINGS = TypeAdapter(list[Finding])


class Findings(BaseModel):
    """The findings ConfigMap."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    http: httpx2.Client
    namespace: str
    name: str

    def write(self, findings: list[Finding], checked_at: datetime) -> None:
        """Replace what the last pass wrote: `findings.json` (a list, empty = all clear) and `checked-at`."""
        data = {
            "findings.json": _FINDINGS.dump_json(findings).decode(),
            "checked-at": checked_at.isoformat(timespec="seconds"),
        }
        path = f"/api/v1/namespaces/{self.namespace}/configmaps"
        response = self.http.patch(
            f"{path}/{self.name}",
            headers={"Content-Type": "application/merge-patch+json"},
            content=json.dumps({"data": data}),
        )
        if response.status_code == 404:  # the first pass
            response = self.http.post(path, json={"metadata": {"name": self.name}, "data": data})
        response.raise_for_status()
