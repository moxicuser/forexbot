"""Monitor paper-session audit heartbeats from a separate process."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import time

from forexbot.alerts import Alerter, create_alerter


HEARTBEAT_EVENTS = {"paper_session_poll", "paper_session_heartbeat"}


def latest_heartbeat(log_path: Path) -> datetime | None:
    if not log_path.exists():
        return None
    with log_path.open("rb") as log_file:
        log_file.seek(0, 2)
        end = log_file.tell()
        log_file.seek(max(0, end - 65536))
        lines = log_file.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        try:
            event = json.loads(line)
            if event.get("event") in HEARTBEAT_EVENTS:
                return datetime.fromisoformat(event["timestamp"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return None


class HeartbeatWatchdog:
    def __init__(
        self,
        log_path: Path,
        alerter: Alerter,
        stale_after: float = 45.0,
        check_interval: float = 10.0,
    ) -> None:
        if stale_after <= 0 or check_interval <= 0:
            raise ValueError("stale_after and check_interval must be positive")
        self.log_path = log_path
        self.alerter = alerter
        self.stale_after = stale_after
        self.check_interval = check_interval
        self._outage_active = False
        self._started_at = datetime.now(UTC)

    def check(self, now: datetime | None = None) -> str:
        current_time = now or datetime.now(UTC)
        heartbeat = latest_heartbeat(self.log_path)
        reference_time = heartbeat or self._started_at
        age_seconds = max(0.0, (current_time - reference_time).total_seconds())
        stale = age_seconds > self.stale_after
        if stale and not self._outage_active:
            self._notify(
                "session_unresponsive",
                {"heartbeat_age_seconds": round(age_seconds, 1), "last_heartbeat": heartbeat.isoformat() if heartbeat else "none"},
            )
            self._outage_active = True
            return "stale"
        if not stale and self._outage_active:
            self._notify("session_recovered", {"last_heartbeat": heartbeat.isoformat() if heartbeat else "none"})
            self._outage_active = False
            return "recovered"
        return "stale" if stale else "healthy"

    def run_forever(self) -> None:
        while True:
            state = self.check()
            print(f"Paper-session heartbeat: {state}")
            time.sleep(self.check_interval)

    def _notify(self, event: str, details: dict[str, object]) -> None:
        try:
            self.alerter.send(event, details)
        except Exception as error:
            print(f"Alert delivery failed for {event}: {type(error).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor ForexBot paper-session heartbeats")
    parser.add_argument("--log", type=Path, default=Path("logs/paper-session.jsonl"))
    parser.add_argument("--stale-after", type=float, default=45.0)
    parser.add_argument("--check-interval", type=float, default=10.0)
    arguments = parser.parse_args()
    watchdog = HeartbeatWatchdog(
        arguments.log,
        create_alerter(),
        stale_after=arguments.stale_after,
        check_interval=arguments.check_interval,
    )
    try:
        watchdog.run_forever()
    except KeyboardInterrupt:
        print("Watchdog stopped.")


if __name__ == "__main__":
    main()
