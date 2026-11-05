"""Anubis's settings, from ANUBIS_* environment variables (Nüwa's env + secretEnv)."""

from datetime import timedelta
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything a pass needs from its environment."""

    model_config = SettingsConfigDict(env_prefix="ANUBIS_", frozen=True)

    # Thoth, read-only: the pod's own Kubernetes token is the login (D104, nuwa-app authentikLogin).
    token_url: str = "https://auth.clockmost.com/application/o/token/"
    authentik_token_file: Path = Path("/var/run/meru/authentik/token")
    thoth_client_id: str = "thoth"
    thoth_url: str = "http://thoth.thoth.svc"

    # A retired app's removedAt + retention live only in its request file (D116), read with a token that can only
    # read that repo.
    gitea_url: str = "https://git.clockmost.com"
    requests_repo: str = "Meru/requests"
    gitea_token: SecretStr

    # Where the findings go (D115): one ConfigMap in its own namespace, which Zabbix reads.
    kubernetes_url: str = "https://kubernetes.default.svc"
    kubernetes_dir: Path = Path("/var/run/meru/kubernetes")  # token, ca.crt
    namespace: str = "anubis"
    argocd_namespace: str = "argocd"  # the direct check for an app: its Application app-<name> (D118)
    findings_name: str = "anubis-findings"

    # Off = a pass only logs the verdicts it would give (as Charon's switches): on once Mario has read a pass's output.
    give_verdicts: bool = False

    # D85: planned or decommissioning longer than this is stuck.
    stuck_after: timedelta = timedelta(days=1)
    # Retained past removedAt + retention + this is a purge overdue: Charon runs once a day, so give it a day.
    purge_grace: timedelta = timedelta(days=1)
