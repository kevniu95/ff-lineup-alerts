"""
Minimal poller skeleton: checks data/schedule.json for any checkpoint due
right now and, for every configured league (ESPN and/or Sleeper -- see
LEAGUE_BUILDERS), sends a Telegram message if it has any alerts; otherwise
no-ops. All configured leagues currently share one Telegram bot/chat, with
each message prefixed by league name -- scope.md's longer-term plan is a
separate bot/thread per league, revisit if that's ever needed.

Intended to run on a Railway cron schedule at a fixed interval. A checkpoint
fires on the first tick at or after its "at" time, within CHECK_WINDOW --
i.e. 0 <= (at - now) < CHECK_WINDOW. This is forward-only (a checkpoint
already in the past is never worth firing on) and, as long as CHECK_WINDOW
equals the cron interval, guarantees exactly one tick catches each
checkpoint: no misses, no duplicates. (If CHECK_WINDOW were symmetric --
checking |at - now| instead -- checkpoints near the midpoint between two
ticks could be caught by both, firing twice.)

--test fire / --test nofire force a message send / no-op without waiting
for a real checkpoint, so the deploy skeleton can be validated on demand.
--test espn / --test sleeper / --test check run real league check(s)
immediately, bypassing the schedule.
"""
import argparse
import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()
from pathlib import Path
from typing import Callable

from ff_lineup_alerts.decision_rules import Alert, AlertKind, run_all
from ff_lineup_alerts.espn_client import EspnClient
from ff_lineup_alerts.league import LeagueClient
from ff_lineup_alerts.sleeper_client import SleeperClient

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_PATH = REPO_ROOT / "data" / "schedule.json"
CHECK_WINDOW = timedelta(minutes=60)  # keep equal to the Railway cron interval

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("poller")


@dataclass
class LeagueConfig:
    name: str
    build_client: Callable[[], LeagueClient]
    # env var whose presence gates whether this league is configured at all --
    # lets you run with just one platform set up without the other erroring.
    required_env: str


# Add an entry here for each new platform/league; poller.py doesn't need any
# other changes to pick it up (see docs/build-plan.md's League-interface note).
LEAGUE_BUILDERS = [
    LeagueConfig(name="ESPN", build_client=EspnClient.from_env, required_env="ESPN_LEAGUE_ID"),
    LeagueConfig(name="Sleeper", build_client=SleeperClient.from_env, required_env="SLEEPER_LEAGUE_ID"),
]


def configured_leagues() -> list[LeagueConfig]:
    leagues = [lc for lc in LEAGUE_BUILDERS if os.environ.get(lc.required_env)]
    if not leagues:
        logger.warning("No leagues configured (no ESPN_LEAGUE_ID or SLEEPER_LEAGUE_ID in env).")
    return leagues


def send_telegram_message(text):
    token = os.environ["BOT_API_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    with urllib.request.urlopen(url, data=data) as resp:
        return json.load(resp)


@dataclass
class AlertOutcome:
    alert: Alert
    applied: bool
    error: str | None = None  # set only when an apply_swap attempt actually failed


def _apply_auto_alerts(client, week: int, alerts: list[Alert]) -> list[AlertOutcome]:
    """
    Executes every AUTO alert immediately via client.apply_swap, if the
    platform's client supports it (ESPN today; Sleeper has no public write
    API -- see docs/scope.md). SUGGEST alerts are never auto-applied.
    """
    outcomes = []
    for alert in alerts:
        if alert.kind != AlertKind.AUTO or not hasattr(client, "apply_swap"):
            outcomes.append(AlertOutcome(alert=alert, applied=False))
            continue
        try:
            client.apply_swap(week, alert.slot, alert.starter, alert.replacement)
            outcomes.append(AlertOutcome(alert=alert, applied=True))
        except Exception as e:
            logger.exception("Failed to apply auto swap for rule %s", alert.rule)
            outcomes.append(AlertOutcome(alert=alert, applied=False, error=str(e)))
    return outcomes


def _format_alert_line(alert: Alert) -> str:
    starter = alert.starter.name if alert.starter else "(empty slot)"
    replacement = alert.replacement.name if alert.replacement else "(no eligible replacement)"
    return f"- {alert.slot}: {starter} -> {replacement} [{alert.reason}]"


def format_alerts_message(league_name: str, week: int, outcomes: list[AlertOutcome], team_link: str) -> str | None:
    """None means silent -- nothing worth notifying about, per scope.md."""
    if not outcomes:
        return None

    applied = [o for o in outcomes if o.alert.kind == AlertKind.AUTO and o.applied]
    failed = [o for o in outcomes if o.alert.kind == AlertKind.AUTO and not o.applied and o.error is not None]
    unsupported = [o for o in outcomes if o.alert.kind == AlertKind.AUTO and not o.applied and o.error is None]
    suggest = [o for o in outcomes if o.alert.kind == AlertKind.SUGGEST]

    lines = [f"[{league_name}] Week {week} lineup check"]
    if applied:
        lines.append("\nAuto-fix applied:")
        lines.extend(_format_alert_line(o.alert) for o in applied)
    if failed:
        lines.append("\nAuto-fix FAILED (needs manual action):")
        lines.extend(f"{_format_alert_line(o.alert)} -- error: {o.error}" for o in failed)
    if unsupported:
        # e.g. Sleeper, which has no public write API to apply this through.
        lines.append("\nAuto-fix candidates (this platform's write-path isn't built):")
        lines.extend(_format_alert_line(o.alert) for o in unsupported)
    if suggest:
        lines.append("\nSuggested (tap-to-approve not wired up yet):")
        lines.extend(_format_alert_line(o.alert) for o in suggest)
    lines.append(f"\n{team_link}")
    return "\n".join(lines)


def run_league_check(league: LeagueConfig) -> str | None:
    client = league.build_client()
    state = client.get_team_state()
    alerts = run_all(state)
    outcomes = _apply_auto_alerts(client, state.week, alerts)
    return format_alerts_message(league.name, state.week, outcomes, client.team_link)


def due_checkpoints(now):
    with open(SCHEDULE_PATH) as f:
        schedule = json.load(f)
    due = []
    for week in schedule["weeks"]:
        for cp in week["checkpoints"]:
            at = datetime.fromisoformat(cp["at"])
            if timedelta(0) <= (at - now) < CHECK_WINDOW:
                due.append((week["week"], cp))
    return due


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test",
        choices=["fire", "nofire", "espn", "sleeper", "check"],
        help=(
            "Force a test fire/no-fire instead of checking real time, run a "
            "single league's real check immediately (espn/sleeper), or run "
            "every configured league's real check immediately (check) -- "
            "all bypass the schedule"
        ),
    )
    args = parser.parse_args()

    if args.test == "fire":
        send_telegram_message("[TEST] Poller fired (forced test-fire case).")
        logger.info("Test fire sent.")
        return
    if args.test == "nofire":
        logger.info("Test no-fire case: intentionally not sending a message.")
        return
    if args.test in ("espn", "sleeper", "check"):
        if args.test == "check":
            leagues = configured_leagues()
        else:
            leagues = [lc for lc in LEAGUE_BUILDERS if lc.name.lower() == args.test]
        for league in leagues:
            message = run_league_check(league)
            if message is None:
                send_telegram_message(f"[TEST] {league.name} check ran -- no alerts right now.")
                logger.info("Test %s check ran with no alerts.", league.name)
            else:
                send_telegram_message(f"[TEST]\n{message}")
                logger.info("Test %s check sent alerts.", league.name)
        return

    now = datetime.now(UTC)
    due = due_checkpoints(now)
    if not due:
        logger.info("No checkpoints due at %s. No-op.", now.isoformat())
        return

    leagues = configured_leagues()
    for week_num, cp in due:
        logger.info("Found due checkpoint: week=%s label=%s at=%s", week_num, cp["label"], cp["at"])
        for league in leagues:
            message = run_league_check(league)
            if message is None:
                logger.info(
                    "%s check: no alerts for week %s checkpoint at %s. No-op.",
                    league.name, week_num, cp["at"],
                )
                continue
            send_telegram_message(message)
            logger.info("Fired %s for week %s checkpoint at %s", league.name, week_num, cp["at"])


if __name__ == "__main__":
    main()
