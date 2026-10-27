"""Tests for the uptime monitor and autoscaler decisions, without HAProxy or Docker.

    python -m pytest infra/tests
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import autoscale  # noqa: E402
import haproxy_stats  # noqa: E402
import uptime_monitor  # noqa: E402
from uptime_monitor import Monitor, Settings, State  # noqa: E402

HEADER = "# pxname,svname,qcur,scur,dreq,dcon,status,rate\n"


def stats(*instances: str, dreq: int = 0, dcon: int = 0, rate: int = 0, queued: int = 0) -> list[dict[str, str]]:
    lines = [f"api_edge,FRONTEND,,0,{dreq},{dcon},OPEN,{rate}"]
    lines += [f"api,api{n},0,0,0,,{status},0" for n, status in enumerate(instances, start=1)]
    lines += [f"api,api{n},0,0,0,,MAINT (resolution),0" for n in range(len(instances) + 1, 11)]
    lines.append(f"api,BACKEND,{queued},0,0,,UP,{rate}")
    return haproxy_stats.parse(HEADER + "\n".join(lines) + "\n")


def monitor(**settings) -> Monitor:
    return Monitor(Settings(**settings), State(since=0))


def test_unused_template_slots_are_not_counted_as_instances():
    rows = stats("UP", "UP 1/2", "DOWN")

    assert [row["svname"] for row in haproxy_stats.instances(rows)] == ["api1", "api2", "api3"]
    assert [row["svname"] for row in haproxy_stats.healthy(rows)] == ["api1", "api2"]


def test_an_outage_alerts_once_after_repeated_failures_and_resolves_with_its_duration():
    watcher = monitor(failures_before_alert=3)

    assert watcher.record(False, None, now=100) == []
    assert watcher.record(False, None, now=110) == []
    [alert] = watcher.record(False, None, now=120)
    assert (alert.kind, alert.resolved) == ("outage", False)
    assert watcher.record(False, None, now=130) == []

    [resolved] = watcher.record(True, None, now=145)
    assert (resolved.kind, resolved.resolved) == ("outage", True)
    assert "45s" in resolved.message


def test_too_few_healthy_instances_alerts_until_they_recover():
    watcher = monitor(min_healthy_instances=2)

    assert watcher.record(True, stats("UP", "UP", "UP"), now=0) == []
    [alert] = watcher.record(True, stats("UP", "DOWN", "DOWN"), now=10)
    assert alert.kind == "instances" and "api2 (DOWN)" in alert.message
    assert watcher.record(True, stats("UP", "DOWN", "DOWN"), now=20) == []
    [resolved] = watcher.record(True, stats("UP", "UP", "DOWN"), now=30)
    assert resolved.resolved


def test_a_spike_in_refused_traffic_is_reported_as_a_possible_ddos():
    watcher = monitor(denied_per_check=100)

    # The first reading is only a baseline, however high the counters are
    assert watcher.record(True, stats("UP", "UP", dreq=5000), now=0) == []
    assert watcher.record(True, stats("UP", "UP", dreq=5050), now=10) == []
    [alert] = watcher.record(True, stats("UP", "UP", dreq=5200, dcon=100), now=20)
    assert alert.kind == "attack" and "250" in alert.message
    # Counters reset when the load balancer restarts; that is not an attack
    assert watcher.record(True, stats("UP", "UP", dreq=3), now=30) == []
    [resolved] = watcher.record(True, stats("UP", "UP", dreq=4), now=40)
    assert resolved.resolved


def test_availability_below_target_alerts_only_after_enough_checks(monkeypatch):
    monkeypatch.setattr(uptime_monitor, "AVAILABILITY_MIN_CHECKS", 10)
    watcher = monitor(failures_before_alert=99, availability_target=99.9)

    alerts = [alert for n in range(10) for alert in watcher.record(n != 0, None, now=n)]

    assert [(alert.kind, alert.resolved) for alert in alerts] == [("availability", False)]
    assert watcher.state.availability() == 90.0


def test_availability_is_kept_across_restarts(tmp_path):
    path = tmp_path / "uptime-status.json"
    state = State(since=1_700_000_000, checks=1000, up_checks=999)
    uptime_monitor.save_state(state, str(path))

    loaded = State.load(str(path), now=1_800_000_000)

    assert (loaded.since, loaded.checks, loaded.up_checks) == (1_700_000_000, 1000, 999)
    assert State.load(str(tmp_path / "missing.json"), now=5).since == 5


def test_autoscaling_adds_one_instance_under_load_and_removes_one_when_quiet():
    policy = autoscale.Policy(minimum=3, maximum=5, target_rate=50)

    assert autoscale.desired_instances(stats("UP", "UP", "UP", rate=200), 3, policy) == 4
    assert autoscale.desired_instances(stats("UP", "UP", "UP", queued=4), 3, policy) == 4
    assert autoscale.desired_instances(stats("UP", "UP", "DOWN"), 3, policy) == 4
    assert autoscale.desired_instances(stats(*["UP"] * 5, rate=400), 5, policy) == 5
    assert autoscale.desired_instances(stats(*["UP"] * 5, rate=20), 5, policy) == 4
    assert autoscale.desired_instances(stats("UP", "UP", "UP", rate=0), 3, policy) == 3
    assert autoscale.desired_instances(stats("UP"), 1, policy) == 3
