"""
Generates the season's lock-check timestamps from ESPN's public scoreboard API.

Every checkpoint comes from bucketing that week's real kickoff times: a new
bucket starts whenever the gap to the previous kickoff exceeds GAP_THRESHOLD,
and each bucket's checkpoint is (bucket's earliest kickoff - PRELOCK_BUFFER).
This naturally produces the right number of checks for holiday weeks
(Thanksgiving, Christmas) and international-game weeks without any
day-of-week special-casing.

All timestamps are stored in UTC. Some late-season weeks may still contain
ESPN placeholder times if the NFL hasn't set them yet (e.g. flex-scheduled
Week 17/18 games) -- this is expected and gets corrected by re-running this
script closer to those weeks (see docs/scope.md's periodic-refresh plan).

Usage:
    python scripts/generate_schedule.py [--year 2026] [--out data/schedule.json]
"""
import argparse
import json
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
NUM_WEEKS = 18
GAP_THRESHOLD = timedelta(hours=3)
PRELOCK_BUFFER = timedelta(minutes=15)
UTC = timezone.utc


def fetch_week(year, week):
    url = f"{BASE_URL}?week={week}&seasontype=2&year={year}"
    with urllib.request.urlopen(url) as resp:
        return json.load(resp)


def kickoff_times(events):
    times = [
        datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(UTC)
        for e in events
    ]
    return sorted(set(times))


def bucketize(times):
    buckets = [[times[0]]]
    for t in times[1:]:
        if t - buckets[-1][-1] > GAP_THRESHOLD:
            buckets.append([t])
        else:
            buckets[-1].append(t)
    return buckets


def generate(year):
    season = {
        "season": year,
        "generated_at": datetime.now(UTC).isoformat(),
        "weeks": [],
    }
    for week in range(1, NUM_WEEKS + 1):
        events = fetch_week(year, week).get("events", [])
        if not events:
            season["weeks"].append({"week": week, "checkpoints": []})
            continue

        buckets = bucketize(kickoff_times(events))
        checkpoints = [
            {
                "label": "prelock",
                "at": (bucket[0] - PRELOCK_BUFFER).isoformat(),
                "bucket_kickoffs": [t.isoformat() for t in bucket],
            }
            for bucket in buckets
        ]
        season["weeks"].append({"week": week, "checkpoints": checkpoints})
    return season


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--out", default="data/schedule.json")
    args = parser.parse_args()

    season = generate(args.year)
    with open(args.out, "w") as f:
        json.dump(season, f, indent=2)

    total = sum(len(w["checkpoints"]) for w in season["weeks"])
    print(f"Wrote {total} checkpoints across {NUM_WEEKS} weeks to {args.out}")


if __name__ == "__main__":
    main()
