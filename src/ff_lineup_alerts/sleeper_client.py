"""
Sleeper data client: hits Sleeper's public REST API directly (no wrapper
library, unlike ESPN's espn-api) and normalizes into the same
RosterPlayer/LineupSlot/TeamState shape as espn_client.py, so both conform
to league.py's LeagueClient protocol. See scripts/spike_sleeper_client.py
for the exploratory version this was promoted from, and docs/scope.md's
open questions for the platform-specific quirks noted below.
"""
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from ff_lineup_alerts.league import LineupSlot, RosterPlayer, TeamState

logger = logging.getLogger("sleeper_client")

BASE = "https://api.sleeper.app/v1"

# Railway sets RAILWAY_VOLUME_MOUNT_PATH automatically for any service with
# an attached Volume, to whatever mount path was chosen in its dashboard --
# so this needs no assumption about a specific volume name or path. Locally
# (no Volume, no env var), falls back to the repo's data/cache/ dir, which
# is fine there since it's not wiped between manual runs the way a fresh
# Railway cron container would be.
CACHE_DIR = Path(os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or Path(__file__).resolve().parents[2] / "data" / "cache")
PLAYERS_CACHE = CACHE_DIR / "sleeper_players.json"
PLAYERS_CACHE_META = CACHE_DIR / "sleeper_players.meta.json"
CACHE_MAX_AGE = timedelta(hours=24)  # matches Sleeper's "don't pull more than once/day" ask

# Sleeper's raw injury_status strings, normalized to league.py's canonical
# vocabulary. PUP/NA/DNR/COV are bucketed as OUT-equivalent -- a player
# carrying any of these clearly isn't startable, even if the exact reason
# differs from a plain Out.
STATUS_MAP = {
    None: "ACTIVE",
    "Out": "OUT",
    "IR": "INJURY_RESERVE",
    "Sus": "SUSPENSION",
    "Questionable": "QUESTIONABLE",
    "Doubtful": "DOUBTFUL",
    "PUP": "INJURY_RESERVE",
    "NA": "OUT",
    "DNR": "OUT",
    "COV": "OUT",
}

# Sleeper's roster_positions can include flex-style slots that aren't a real
# player position -- map each to the positions it accepts.
FLEX_ELIGIBILITY = {
    "FLEX": {"RB", "WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
    "WRRB_FLEX": {"WR", "RB"},
    "REC_FLEX": {"WR", "TE"},
}


def _normalize_status(raw_status: str | None) -> str:
    return STATUS_MAP.get(raw_status, raw_status or "ACTIVE")


def _eligible_slots_for(fantasy_positions: list[str], roster_position_labels: set[str]) -> list[str]:
    positions = set(fantasy_positions or [])
    eligible = []
    for label in roster_position_labels:
        if label in ("BN", "IR"):
            eligible.append(label)
        elif label in FLEX_ELIGIBILITY:
            if positions & FLEX_ELIGIBILITY[label]:
                eligible.append(label)
        elif label in positions:
            eligible.append(label)
    return eligible


def _cache_is_fresh() -> bool:
    if not (PLAYERS_CACHE.exists() and PLAYERS_CACHE_META.exists()):
        return False
    try:
        fetched_at = datetime.fromisoformat(json.loads(PLAYERS_CACHE_META.read_text())["fetched_at"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return False
    return datetime.now(timezone.utc) - fetched_at < CACHE_MAX_AGE


def _load_players() -> dict:
    """~14MB static file Sleeper asks not be pulled more than once/day."""
    if _cache_is_fresh():
        return json.loads(PLAYERS_CACHE.read_text())

    logger.info("Sleeper player cache missing or stale, re-fetching from %s", CACHE_DIR)
    resp = requests.get(f"{BASE}/players/nfl")
    resp.raise_for_status()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PLAYERS_CACHE.write_text(resp.text)
    PLAYERS_CACHE_META.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat()}))
    return json.loads(resp.text)


def _load_week_schedule(season: str, week: int) -> dict[str, str]:
    """Team abbreviation -> that game's status ('pre_game', 'complete', etc.),
    from Sleeper's undocumented schedule endpoint (no per-team bye-week field
    exists in the documented players/nfl dump -- see scope.md)."""
    resp = requests.get(f"https://api.sleeper.app/schedule/nfl/regular/{season}")
    resp.raise_for_status()
    team_status = {}
    for g in resp.json():
        if g["week"] != week:
            continue
        team_status[g["home"]] = g["status"]
        team_status[g["away"]] = g["status"]
    return team_status


def _load_projections(season: str, week: int) -> dict[str, float]:
    """Undocumented endpoint -- see scope.md's projection-freshness open
    question; stability isn't guaranteed the way a documented API's would be."""
    resp = requests.get(
        f"https://api.sleeper.app/projections/nfl/{season}/{week}",
        params={"season_type": "regular"},
    )
    resp.raise_for_status()
    return {
        entry["player_id"]: entry["stats"].get("pts_ppr", 0)
        for entry in resp.json()
        if entry.get("stats")
    }


class SleeperClient:
    def __init__(self, league_id: str, username: str):
        self.league_id = league_id
        self.username = username

    @classmethod
    def from_env(cls) -> "SleeperClient":
        return cls(
            league_id=os.environ["SLEEPER_LEAGUE_ID"],
            username=os.environ["SLEEPER_USERNAME"],
        )

    @property
    def team_link(self) -> str:
        return f"https://sleeper.com/leagues/{self.league_id}/team"

    def get_team_state(self) -> TeamState:
        state = requests.get(f"{BASE}/state/nfl").json()
        current_week, season = state["week"], state["season"]

        users = requests.get(f"{BASE}/league/{self.league_id}/users").json()
        my_user = next(u for u in users if u["display_name"] == self.username)

        rosters = requests.get(f"{BASE}/league/{self.league_id}/rosters").json()
        my_roster = next(r for r in rosters if r["owner_id"] == my_user["user_id"])

        league = requests.get(f"{BASE}/league/{self.league_id}").json()
        roster_positions = league["roster_positions"]  # e.g. QB,RB,RB,WR,WR,TE,FLEX,K,DEF,BN...
        starting_slots = [p for p in roster_positions if p != "BN"]
        roster_position_labels = set(roster_positions)

        players = _load_players()
        team_status = _load_week_schedule(season, current_week)
        projections = _load_projections(season, current_week)

        def to_roster_player(player_id: str) -> RosterPlayer:
            p = players.get(player_id, {})
            team = p.get("team")
            game_status = team_status.get(team)
            return RosterPlayer(
                name=p.get("full_name", player_id),
                status=_normalize_status(p.get("injury_status")),
                on_bye=team is not None and game_status is None,
                has_played=game_status is not None and game_status != "pre_game",
                projection=projections.get(player_id, 0) or 0,
                eligible_slots=_eligible_slots_for(p.get("fantasy_positions"), roster_position_labels),
            )

        lineup = []
        for slot_label, player_id in zip(starting_slots, my_roster["starters"]):
            if player_id == "0":
                lineup.append(LineupSlot(slot=slot_label, player=None))
                continue
            lineup.append(LineupSlot(slot=slot_label, player=to_roster_player(player_id)))

        bench_ids = [pid for pid in my_roster["players"] if pid not in my_roster["starters"]]
        bench = [to_roster_player(pid) for pid in bench_ids]

        logger.info(
            "Fetched Sleeper team state: week=%s starters=%d bench=%d",
            current_week, len(lineup), len(bench),
        )
        return TeamState(week=current_week, lineup=lineup, bench=bench)
