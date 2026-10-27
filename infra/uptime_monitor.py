"""Uptime monitoring and alerts for the API (R-07).

Every MONITOR_INTERVAL_SECONDS this checks the API's health through the edge
load balancer, as a client would, and reads the load balancer's status. It
raises an alert when:

- the API has failed MONITOR_FAILURES_BEFORE_ALERT checks in a row (outage),
- fewer than MONITOR_MIN_HEALTHY_INSTANCES instances pass their health checks,
- the edge refused more than MONITOR_DENIED_PER_CHECK requests or connections
  since the last check (a likely DDoS or abusive client), or
- measured availability falls below AVAILABILITY_TARGET (99.9 by default).

Each alert is sent once when it starts and once when it is resolved: to the
console, as a JSON line in MONITOR_ALERT_LOG, to ALERT_WEBHOOK_URL (Slack or
Discord style) and by email to ALERT_EMAIL_TO through the SMTP_* settings of
backend/.env, whichever are configured. Availability is kept in
MONITOR_STATE_FILE so it survives a restart of the monitor.

    python infra/uptime_monitor.py

Standard library only. In production run it outside the hosting environment
it watches, so it keeps alerting when that environment is down.
"""
import http.client
import json
import logging
import os
import smtplib
import socket
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import haproxy_stats

logger = logging.getLogger("uptime")

# Availability is only judged after this many checks (10 minutes at the
# default interval), so one failure at start-up does not raise an alert
AVAILABILITY_MIN_CHECKS = 60


@dataclass(frozen=True)
class Settings:
    health_url: str = "https://edge:8443/health"
    # Name on the certificate; the edge is reached by its Docker name
    tls_name: str = "localhost"
    ca_file: str = "/certs/ca.pem"
    stats_url: str = "http://edge:8404/stats"
    interval_seconds: float = 10
    timeout_seconds: float = 5
    failures_before_alert: int = 3
    min_healthy_instances: int = 2
    denied_per_check: int = 100
    availability_target: float = 99.9
    state_file: str = "/logs/uptime-status.json"
    alert_log: str = "/logs/alerts.log"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        defaults = cls()
        return cls(
            health_url=env("MONITOR_URL", defaults.health_url),
            tls_name=env("MONITOR_TLS_NAME", defaults.tls_name),
            ca_file=env("MONITOR_CA_FILE", defaults.ca_file),
            stats_url=env("MONITOR_STATS_URL", defaults.stats_url),
            interval_seconds=float(env("MONITOR_INTERVAL_SECONDS", defaults.interval_seconds)),
            timeout_seconds=float(env("MONITOR_TIMEOUT_SECONDS", defaults.timeout_seconds)),
            failures_before_alert=int(env("MONITOR_FAILURES_BEFORE_ALERT", defaults.failures_before_alert)),
            min_healthy_instances=int(env("MONITOR_MIN_HEALTHY_INSTANCES", defaults.min_healthy_instances)),
            denied_per_check=int(env("MONITOR_DENIED_PER_CHECK", defaults.denied_per_check)),
            availability_target=float(env("AVAILABILITY_TARGET", defaults.availability_target)),
            state_file=env("MONITOR_STATE_FILE", defaults.state_file),
            alert_log=env("MONITOR_ALERT_LOG", defaults.alert_log),
        )


@dataclass(frozen=True)
class Alert:
    kind: str  # outage, instances, attack or availability
    resolved: bool
    message: str


@dataclass
class State:
    since: float
    checks: int = 0
    up_checks: int = 0
    failures_in_row: int = 0
    down_since: float | None = None
    last_denied: int | None = None
    # Alert kinds currently open
    open: set[str] = field(default_factory=set)

    def availability(self) -> float:
        return 100.0 if not self.checks else 100.0 * self.up_checks / self.checks

    def to_json(self) -> dict:
        return {
            "since": _iso(self.since),
            "checks": self.checks,
            "upChecks": self.up_checks,
            "availabilityPercent": round(self.availability(), 4),
            "openAlerts": sorted(self.open),
        }

    @classmethod
    def load(cls, path: str, now: float) -> "State":
        """Counts from an earlier run, so availability covers the whole election period."""
        try:
            saved = json.loads(Path(path).read_text(encoding="utf-8"))
            return cls(
                since=datetime.fromisoformat(saved["since"]).timestamp(),
                checks=int(saved["checks"]),
                up_checks=int(saved["upChecks"]),
            )
        except (OSError, ValueError, KeyError):
            return cls(since=now)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _duration(seconds: float) -> str:
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes}m {seconds}s" if minutes else f"{seconds}s"


class Monitor:
    def __init__(self, settings: Settings, state: State):
        self.settings = settings
        self.state = state

    def record(self, up: bool, rows: list[dict[str, str]] | None, now: float) -> list[Alert]:
        """Takes one health check result and the load balancer status (None if
        it could not be read), and returns the alerts that start or end."""
        state, settings = self.state, self.settings
        alerts: list[Alert] = []
        state.checks += 1

        if up:
            state.up_checks += 1
            if "outage" in state.open:
                alerts.append(self._close("outage", f"API available again after {_duration(now - state.down_since)}"))
            state.failures_in_row = 0
            state.down_since = None
        else:
            state.failures_in_row += 1
            if state.down_since is None:
                state.down_since = now
            if state.failures_in_row >= settings.failures_before_alert:
                alerts += self._open("outage", f"API unavailable: {state.failures_in_row} health checks "
                                               f"failed in a row since {_iso(state.down_since)}")

        if rows is not None:
            alerts += self._check_instances(rows)
            alerts += self._check_denied(rows)

        availability = state.availability()
        if state.checks >= AVAILABILITY_MIN_CHECKS and availability < settings.availability_target:
            alerts += self._open("availability", f"Availability {availability:.3f}% is below the "
                                                 f"{settings.availability_target}% target "
                                                 f"(since {_iso(state.since)})")
        elif "availability" in state.open:
            alerts.append(self._close("availability", f"Availability back to {availability:.3f}%"))
        return alerts

    def _check_instances(self, rows: list[dict[str, str]]) -> list[Alert]:
        running = haproxy_stats.instances(rows)
        healthy = haproxy_stats.healthy(rows)
        if len(healthy) < self.settings.min_healthy_instances:
            # Stopped containers leave Docker's DNS, so they are not listed at all
            failing = ", ".join(f"{row['svname']} ({row['status']})" for row in running if row not in healthy)
            return self._open("instances", f"Only {len(healthy)} API instances healthy, minimum "
                                           f"{self.settings.min_healthy_instances}. "
                                           f"Failing health checks: {failing or 'none; the others have stopped'}")
        if "instances" in self.state.open:
            return [self._close("instances", f"{len(healthy)} API instances healthy again")]
        return []

    def _check_denied(self, rows: list[dict[str, str]]) -> list[Alert]:
        total = haproxy_stats.denied(rows)
        previous, self.state.last_denied = self.state.last_denied, total
        # No baseline yet, or the load balancer restarted and its counters reset
        if previous is None or total < previous:
            return []
        recent = total - previous
        if recent > self.settings.denied_per_check:
            return self._open("attack", f"Possible DDoS: the edge refused {recent} requests or connections "
                                        f"in the last {_duration(self.settings.interval_seconds)}")
        if "attack" in self.state.open:
            return [self._close("attack", "Refused traffic back to normal")]
        return []

    def _open(self, kind: str, message: str) -> list[Alert]:
        if kind in self.state.open:
            return []
        self.state.open.add(kind)
        return [Alert(kind, False, message)]

    def _close(self, kind: str, message: str) -> Alert:
        self.state.open.discard(kind)
        return Alert(kind, True, message)


def check_health(settings: Settings) -> bool:
    url = urllib.parse.urlsplit(settings.health_url)
    context = ssl.create_default_context(cafile=settings.ca_file)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    # The development certificate (npm run cert:dev) has no Authority Key
    # Identifier, which Python's strict mode requires; the chain and name are
    # still verified
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    try:
        sock = socket.create_connection((url.hostname, url.port or 443), timeout=settings.timeout_seconds)
        connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=settings.timeout_seconds)
        # Verified against the certificate's name, not the Docker host name
        connection.sock = context.wrap_socket(sock, server_hostname=settings.tls_name)
        try:
            connection.request("GET", url.path or "/", headers={"Host": settings.tls_name})
            response = connection.getresponse()
            return response.status == 200 and json.loads(response.read()).get("status") == "ok"
        finally:
            connection.close()
    except (OSError, ValueError, http.client.HTTPException) as exc:
        logger.info("Health check failed: %s", exc)
        return False


class Notifier:
    def __init__(self, settings: Settings):
        self.alert_log = Path(settings.alert_log)
        self.webhook_url = os.environ.get("ALERT_WEBHOOK_URL")
        self.email_to = os.environ.get("ALERT_EMAIL_TO")

    def send(self, alert: Alert, now: float) -> None:
        status = "RESOLVED" if alert.resolved else "ALERT"
        text = f"[{status}] {alert.message}"
        (logger.info if alert.resolved else logger.error)(text)
        entry = {"time": _iso(now), "event": f"uptime.{alert.kind}",
                 "status": status.lower(), "message": alert.message}
        try:
            self.alert_log.parent.mkdir(parents=True, exist_ok=True)
            with self.alert_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry) + "\n")
        except OSError:
            logger.exception("Unable to write alert log")
        if self.webhook_url:
            self._webhook(text)
        if self.email_to:
            self._email(f"E-voting API {status.lower()}: {alert.kind}", text)

    def _webhook(self, text: str) -> None:
        # "text" for Slack, "content" for Discord
        body = json.dumps({"text": text, "content": text}).encode()
        request = urllib.request.Request(self.webhook_url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(request, timeout=10).close()
        except OSError:
            logger.exception("Unable to send alert webhook")

    def _email(self, subject: str, text: str) -> None:
        # Same settings as backend/email.py
        env = os.environ.get
        host, sender = env("SMTP_HOST"), env("SMTP_FROM_EMAIL")
        if not host or not sender:
            logger.error("ALERT_EMAIL_TO is set but SMTP_HOST or SMTP_FROM_EMAIL is not")
            return
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = self.email_to
        message.set_content(text)
        use_ssl = env("SMTP_USE_SSL", "").strip().lower() in {"1", "true", "yes", "on"}
        try:
            smtp_type = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
            with smtp_type(host, int(env("SMTP_PORT", "587")), timeout=15) as server:
                if not use_ssl:
                    server.starttls()
                if env("SMTP_USERNAME"):
                    server.login(env("SMTP_USERNAME"), env("SMTP_PASSWORD", ""))
                server.send_message(message)
        except (OSError, smtplib.SMTPException):
            logger.exception("Unable to send alert email")


def save_state(state: State, path: str) -> None:
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(state.to_json(), indent=2), encoding="utf-8")
        temporary.replace(target)
    except OSError:
        logger.exception("Unable to save uptime state")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    settings = Settings.from_env()
    monitor = Monitor(settings, State.load(settings.state_file, time.time()))
    notifier = Notifier(settings)
    logger.info("Monitoring %s every %ss; availability so far %.3f%%",
                settings.health_url, settings.interval_seconds, monitor.state.availability())
    while True:
        started = time.monotonic()
        up = check_health(settings)
        try:
            rows = haproxy_stats.fetch(settings.stats_url, settings.timeout_seconds)
        except (OSError, ValueError) as exc:
            logger.warning("Load balancer status unavailable: %s", exc)
            rows = None
        now = time.time()
        for alert in monitor.record(up, rows, now):
            notifier.send(alert, now)
        save_state(monitor.state, settings.state_file)
        time.sleep(max(0.0, settings.interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
