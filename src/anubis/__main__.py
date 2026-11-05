"""anubis: Meru's verdicts (D53, D85, D114).

Once a day, as a CronJob: it checks what scanners stopped seeing directly and gives the verdict - missing or retired
(D53, D118) - and reports every stuck app - planned or decommissioning over a day, retained past its retention - plus
what the checks found into the ConfigMap anubis-findings, which Zabbix reads (D115). One pass, then
exit - 0 when the findings were written (finding something is not a failure), 1 when it couldn't look, so the
CronJob's last successful run is what Zabbix watches for Anubis itself. Later it is the only one that retires.
"""

import logging
import ssl
import sys
from datetime import UTC, datetime

import httpx2

from anubis.checks import Finding, Limits, retained, stuck
from anubis.cluster import Findings
from anubis.config import Settings
from anubis.lookups import Lookups
from anubis.request_files import RequestFiles
from anubis.thoth import Item, Thoth
from anubis.tokens import login
from anubis.unseen import judge

log = logging.getLogger("anubis")


def weigh(
    thoth: Thoth, requests: RequestFiles, lookups: Lookups, now: datetime, limits: Limits, *, give: bool = True
) -> list[Finding]:
    """Every stuck app and unseen item, in a stable order; verdicts given on the way.

    A repo it can't see fails the pass instead of dating nothing.
    """
    requests.check_visible()
    findings = judge_unseen(thoth, requests, lookups, give=give)
    for status in ("planned", "decommissioning"):
        for app in thoth.apps(status):
            if finding := stuck(app.key, status, thoth.since(app), now, limits):
                findings.append(finding)
    for app in thoth.apps("retained"):
        if finding := retained(app.key, thoth.since(app), requests.read(app.key), now, limits):
            findings.append(finding)
    return sorted(findings, key=lambda f: (f.kind, f.app))


def judge_unseen(thoth: Thoth, requests: RequestFiles, lookups: Lookups, *, give: bool) -> list[Finding]:
    """Check each unseen item directly and give the verdict (D53, D118) - or, switched off, only log it.

    One item lost by several scanners is judged once.
    """
    lost: dict[tuple[str, str], tuple[Item, list[str]]] = {}
    for entry in thoth.unseen():
        lost.setdefault((entry.item.type, entry.item.key), (entry.item, []))[1].append(entry.source)
    findings: list[Finding] = []
    for item, sources in lost.values():
        decision = judge(item, sources, lookups.look(item.type, item.key), declared=_declared(requests, item))
        if decision.verdict and decision.verdict != item.status:
            if give:
                thoth.verdict(item, decision.verdict, decision.reason)
            log.info(
                "%s%s %s %s: %s", "" if give else "would be ", decision.verdict, item.type, item.key, decision.reason
            )
        if decision.finding:
            findings.append(decision.finding)
    return findings


def _declared(requests: RequestFiles, item: Item) -> bool:
    """Whether a request still declares it: an app whose request file exists and isn't removed."""
    if item.type != "app":
        return False
    request = requests.read(item.key)
    return request is not None and not request.spec.removed


def run() -> int:
    """One pass. Returns the exit code."""
    settings = Settings()
    now = datetime.now(UTC)
    kubernetes_token = (settings.kubernetes_dir / "token").read_text().strip()
    with (
        httpx2.Client() as authentik,
        httpx2.Client(
            base_url=settings.gitea_url,
            headers={"Authorization": f"token {settings.gitea_token.get_secret_value()}"},
        ) as gitea,
        httpx2.Client(
            base_url=settings.kubernetes_url,
            headers={"Authorization": f"Bearer {kubernetes_token}"},
            verify=ssl.create_default_context(cafile=settings.kubernetes_dir / "ca.crt"),
        ) as kubernetes,
    ):
        try:
            token = login(authentik, settings.token_url, settings.thoth_client_id, settings.authentik_token_file)
            with httpx2.Client(
                base_url=settings.thoth_url, headers={"Authorization": f"Bearer {token.get_secret_value()}"}
            ) as thoth:
                findings = weigh(
                    Thoth(http=thoth),
                    RequestFiles(http=gitea, repo=settings.requests_repo),
                    Lookups(http=kubernetes, argocd_namespace=settings.argocd_namespace),
                    now,
                    Limits(stuck_after=settings.stuck_after, purge_grace=settings.purge_grace),
                    give=settings.give_verdicts,
                )
        except httpx2.HTTPError:
            log.exception("couldn't weigh: findings left as the last pass wrote them")
            return 1
        Findings(http=kubernetes, namespace=settings.namespace, name=settings.findings_name).write(findings, now)
    for finding in findings:
        log.info("%s %s: %s", finding.kind, finding.app, finding.detail)
    log.info("pass done: %d stuck", len(findings))
    return 0


def main() -> None:
    """Set up logging, run one pass and exit with its code."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    sys.exit(run())


if __name__ == "__main__":
    main()
