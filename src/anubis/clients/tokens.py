"""A short-lived Thoth token (client_credentials), fetched once per pass.

The login is the pod's own Kubernetes token (D104: nuwa-app authentikLogin, audience authentik, kubelet-refreshed),
sent as the client assertion - no password anywhere. Authentik checks it against k3s's key and answers with the
rights of the groups that list this workload (infra blueprints thoth.yaml: thoth.read). A pass takes seconds and the
token lasts 10 minutes, so there is no cache.
"""

from pathlib import Path

import httpx2
from pydantic import SecretStr

from anubis.clients.incoming import Incoming

ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


class _TokenAnswer(Incoming):
    access_token: SecretStr


def login(http: httpx2.Client, token_url: str, client_id: str, token_file: Path) -> SecretStr:
    """Exchange the pod's Kubernetes token for a token for `client_id`'s provider."""
    response = http.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "scope": client_id,  # the provider's own scope mapping (thoth permissions)
            "client_assertion_type": ASSERTION,
            "client_assertion": token_file.read_text().strip(),
        },
    )
    response.raise_for_status()
    return _TokenAnswer.model_validate_json(response.content).access_token
