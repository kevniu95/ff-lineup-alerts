"""
Minimal poller skeleton: checks data/schedule.json for any checkpoint due
right now and sends a Telegram message if so; otherwise no-ops.

Intended to run on a Railway cron schedule (e.g. every 15 minutes) with
CHECK_WINDOW wide enough to not miss a checkpoint between runs.

--test fire / --test nofire force a message send / no-op without waiting
for a real checkpoint, so the deploy skeleton can be validated on demand.
"""
import argparse
import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
SCHEDULE_PATH = Path(__file__).parent / "data" / "schedule.json"
CHECK_WINDOW = timedelta(minutes=10)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("poller")


def send_telegram_message(text):
    token = os.environ["BOT_API_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    with urllib.request.urlopen(url, data=data) as resp:
        return json.load(resp)


def due_checkpoints(now):
    with open(SCHEDULE_PATH) as f:
        schedule = json.load(f)
    due = []
    for week in schedule["weeks"]:
        for cp in week["checkpoints"]:
            at = datetime.fromisoformat(cp["at"])
            if abs(at - now) <= CHECK_WINDOW:
                due.append((week["week"], cp))
    return due


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test",
        choices=["fire", "nofire"],
        help="Force a test fire/no-fire instead of checking real time",
    )
    args = parser.parse_args()

    if args.test == "fire":
        send_telegram_message("[TEST] Poller fired (forced test-fire case).")
        logger.info("Test fire sent.")
        return
    if args.test == "nofire":
        logger.info("Test no-fire case: intentionally not sending a message.")
        return

    now = datetime.now(UTC)
    due = due_checkpoints(now)
    if not due:
        logger.info("No checkpoints due at %s. No-op.", now.isoformat())
        return

    for week_num, cp in due:
        logger.info("Found due checkpoint: week=%s label=%s at=%s", week_num, cp["label"], cp["at"])
        send_telegram_message(
            f"[Week {week_num}] Lineup check due ({cp['label']}) — poller skeleton test."
        )
        logger.info("Fired for week %s checkpoint at %s", week_num, cp["at"])


if __name__ == "__main__":
    main()
