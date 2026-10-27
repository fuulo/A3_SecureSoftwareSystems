"""Scales the API instances with load (R-07).

Reads the request rate and queue from the load balancer's status page and
runs "docker compose up --scale api=N" to keep each instance near
--target requests per second, between --min and --max instances. It adds or
removes one instance at a time, waiting --cooldown seconds between changes.

Run it on the Docker host from the repository root, next to docker-compose.yml:

    python infra/autoscale.py [--min 3] [--max 10] [--target 50]

Standard library only. It runs on the host rather than in a container so
that no container needs access to the Docker socket.
"""
import argparse
import logging
import math
import subprocess
import sys
import time
from dataclasses import dataclass

import haproxy_stats

logger = logging.getLogger("autoscale")

# Slots in the HAProxy server template (infra/haproxy.cfg)
TEMPLATE_SLOTS = 10


@dataclass(frozen=True)
class Policy:
    minimum: int = 3
    maximum: int = TEMPLATE_SLOTS
    # Requests per second one instance should handle
    target_rate: float = 50
    # Fraction of the target below which an instance is removed
    scale_in_below: float = 0.5


def desired_instances(rows: list[dict[str, str]], running: int, policy: Policy) -> int:
    """How many instances to run, at most one more or fewer than now."""
    rate = haproxy_stats.number(haproxy_stats.backend(rows), "rate")
    queued = haproxy_stats.number(haproxy_stats.backend(rows), "qcur")
    healthy = len(haproxy_stats.healthy(rows))

    if running < policy.minimum:
        wanted = policy.minimum
    elif queued > 0 or healthy < running or rate > running * policy.target_rate:
        # Requests waiting, instances failing or over the target rate
        wanted = running + 1
    elif rate < (running - 1) * policy.target_rate * policy.scale_in_below:
        # Still comfortably under the target with one instance fewer
        wanted = max(running - 1, math.ceil(rate / policy.target_rate))
    else:
        wanted = running
    return max(policy.minimum, min(policy.maximum, wanted))


def scale(count: int) -> bool:
    command = ["docker", "compose", "up", "--detach", "--no-recreate", "--scale", f"api={count}", "api"]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        logger.error("Scaling failed: %s", result.stderr.strip())
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Scale the API instances with load.")
    parser.add_argument("--stats-url", default="http://127.0.0.1:8404/stats")
    parser.add_argument("--min", type=int, default=Policy.minimum)
    parser.add_argument("--max", type=int, default=Policy.maximum)
    parser.add_argument("--target", type=float, default=Policy.target_rate,
                        help="requests per second per instance")
    parser.add_argument("--interval", type=float, default=10, help="seconds between checks")
    parser.add_argument("--cooldown", type=float, default=60, help="seconds between changes")
    parser.add_argument("--dry-run", action="store_true", help="report decisions without scaling")
    args = parser.parse_args()
    if not 1 <= args.min <= args.max <= TEMPLATE_SLOTS:
        sys.exit(f"Need 1 <= --min <= --max <= {TEMPLATE_SLOTS} (slots in infra/haproxy.cfg)")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    policy = Policy(args.min, args.max, args.target)
    last_change = 0.0
    while True:
        try:
            rows = haproxy_stats.fetch(args.stats_url)
        except (OSError, ValueError) as exc:
            logger.warning("Load balancer status unavailable: %s", exc)
            rows = None
        if rows is not None:
            running = len(haproxy_stats.instances(rows))
            wanted = desired_instances(rows, running, policy)
            if wanted != running and time.monotonic() - last_change >= args.cooldown:
                logger.info("Scaling API from %d to %d instances", running, wanted)
                if args.dry_run or scale(wanted):
                    last_change = time.monotonic()
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
