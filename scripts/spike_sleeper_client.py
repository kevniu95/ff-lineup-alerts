"""
Sleeper data spike -- see docs/build-plan.md step 1 / docs/scope.md Autonomy section.

Throwaway: pulls our own team's roster + lineup via Sleeper's public REST API
and checks it against the auto/suggest data-needs table in docs/scope.md.

Findings vs. ESPN spike (scripts/spike_espn_client.py):
  - status (Out/IR/Questionable/Doubtful) -> players.json's injury_status field,
    same idea as ESPN's injuryStatus.
  - bye week -> NOT in players.json at all. Derived instead from an
    undocumented schedule endpoint (api.sleeper.app/schedule/nfl/regular/{season}):
    a team missing from a given week's home/away list is on bye.
  - projections -> NOT in the documented league/roster endpoints. Pulled from
    an undocumented endpoint (api.sleeper.app/projections/nfl/{season}/{week}).
    Being undocumented, both of these are a stability risk worth flagging.
  - exact kickoff time -> the schedule endpoint only gives a date, not a
    time, unlike ESPN's per-player game_date. Not a blocker: we already
    generate data/schedule.json from ESPN's scoreboard API as the shared
    kickoff-time source regardless of which platform's league we're checking.
  - empty starting slot -> not a per-slot object like ESPN's box score.
    Starters is a flat list of player_ids aligned positionally to the
    non-'BN' entries in the league's roster_positions list; an empty slot
    shows up as the literal string "0" in starters.

Run: .venv/bin/python scripts/spike_sleeper_client.py
"""
import json
import os
from pathlib import Path

import requests

BASE = "https://api.sleeper.app/v1"
PLAYERS_CACHE = Path(__file__).parent.parent / "data" / "cache" / "sleeper_players.json"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_players() -> dict:
    """~14MB static file ESPN doesn't need an equivalent of -- cache it."""
    if not PLAYERS_CACHE.exists():
        PLAYERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(f"{BASE}/players/nfl")
        resp.raise_for_status()
        PLAYERS_CACHE.write_text(resp.text)
    return json.loads(PLAYERS_CACHE.read_text())


def load_bye_weeks(season: str, current_week: int, weeks_ahead: int = 4) -> dict[int, set[str]]:
    resp = requests.get(f"https://api.sleeper.app/schedule/nfl/regular/{season}")
    resp.raise_for_status()
    games = resp.json()
    playing_by_week: dict[int, set[str]] = {}
    all_teams: set[str] = set()
    for g in games:
        playing_by_week.setdefault(g["week"], set()).update([g["home"], g["away"]])
        all_teams |= {g["home"], g["away"]}
    return {
        week: all_teams - playing_by_week.get(week, set())
        for week in range(current_week, current_week + weeks_ahead)
    }


def load_projections(season: str, week: int) -> dict[str, float]:
    resp = requests.get(
        f"https://api.sleeper.app/projections/nfl/{season}/{week}",
        params={"season_type": "regular"},
    )
    resp.raise_for_status()
    return {
        entry["player_id"]: entry["stats"].get("pts_ppr")
        for entry in resp.json()
        if entry.get("stats")
    }


def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")
    league_id = os.environ["SLEEPER_LEAGUE_ID"]

    state = requests.get(f"{BASE}/state/nfl").json()
    current_week, season = state["week"], state["season"]

    users = requests.get(f"{BASE}/league/{league_id}/users").json()
    my_user = next(u for u in users if u["display_name"] == "kniu95")

    rosters = requests.get(f"{BASE}/league/{league_id}/rosters").json()
    my_roster = next(r for r in rosters if r["owner_id"] == my_user["user_id"])

    league = requests.get(f"{BASE}/league/{league_id}").json()
    roster_positions = league["roster_positions"]  # e.g. QB,RB,RB,WR,WR,TE,FLEX,FLEX,K,DEF,BN...
    starting_slots = [p for p in roster_positions if p != "BN"]

    players = load_players()
    bye_weeks = load_bye_weeks(season, current_week)
    projections = load_projections(season, current_week)

    print(f"Current week: {current_week}  |  season: {season}")
    print(f"Roster positions: {roster_positions}")

    print("\n--- Starting lineup ---")
    for slot, player_id in zip(starting_slots, my_roster["starters"]):
        if player_id == "0":
            print(f"slot={slot:6s}  <<< EMPTY SLOT")
            continue
        p = players.get(player_id, {})
        team = p.get("team")
        upcoming_bye = next((wk for wk, teams in bye_weeks.items() if team in teams), None)
        print(
            f"slot={slot:6s} {p.get('full_name', player_id):25s} "
            f"status={p.get('injury_status') or 'ACTIVE':12s} "
            f"upcoming_bye={upcoming_bye} "
            f"proj={projections.get(player_id)}"
        )

    print("\n--- Bench ---")
    bench_ids = [pid for pid in my_roster["players"] if pid not in my_roster["starters"]]
    for player_id in bench_ids:
        p = players.get(player_id, {})
        team = p.get("team")
        upcoming_bye = next((wk for wk, teams in bye_weeks.items() if team in teams), None)
        print(
            f"{p.get('full_name', player_id):25s} "
            f"status={p.get('injury_status') or 'ACTIVE':12s} "
            f"upcoming_bye={upcoming_bye} "
            f"proj={projections.get(player_id)}"
        )


if __name__ == "__main__":
    main()
