"""
ESPN data client: wraps `espn-api` to expose exactly the fields the decision
rules in decision_rules.py need, per the auto/suggest data-needs table in
docs/scope.md. See scripts/spike_espn_client.py for the exploratory version
this was promoted from.

Built entirely from box_scores()'s lineup (a BoxPlayer per roster spot,
covering starters/bench/IR alike) rather than team.roster -- BoxPlayer
already carries week-specific .projected_points and .on_bye_week, which
team.roster's plain Player does not (that only has season-level
projected_total_points, and bye weeks would need deriving from .schedule).
"""
import logging
import os
from dataclasses import dataclass

from espn_api.football import League

logger = logging.getLogger("espn_client")

BENCH_SLOTS = {"BE", "IR"}


@dataclass
class RosterPlayer:
    name: str
    status: str  # raw ESPN injuryStatus string, e.g. "ACTIVE", "OUT", "QUESTIONABLE"
    on_bye: bool
    has_played: bool  # this week's game is over (or well underway) for this player
    projection: float
    eligible_slots: list[str]


@dataclass
class LineupSlot:
    slot: str
    player: RosterPlayer | None  # None means the slot is empty


@dataclass
class TeamState:
    week: int
    lineup: list[LineupSlot]
    bench: list[RosterPlayer]


def _to_roster_player(bp) -> RosterPlayer:
    return RosterPlayer(
        name=bp.name,
        status=bp.injuryStatus,
        on_bye=bp.on_bye_week,
        # espn-api's game_played is really a binary "kickoff + 3hrs has passed"
        # flag despite the 0-100 "percent of game played" naming.
        has_played=bp.game_played >= 100,
        projection=bp.projected_points,
        eligible_slots=list(bp.eligibleSlots),
    )


class EspnClient:
    def __init__(self, league_id: int, year: int, espn_s2: str, swid: str, team_id: int):
        self.league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
        self.team_id = team_id

    @classmethod
    def from_env(cls) -> "EspnClient":
        return cls(
            league_id=int(os.environ["ESPN_LEAGUE_ID"]),
            year=int(os.environ.get("ESPN_YEAR", "2026")),
            espn_s2=os.environ["ESPN_S2"],
            swid=os.environ["ESPN_SWID"],
            team_id=int(os.environ["ESPN_TEAM_ID"]),
        )

    def get_team_state(self) -> TeamState:
        current_week = self.league.current_week
        box = next(
            b for b in self.league.box_scores(current_week)
            if self.team_id in (b.home_team.team_id, b.away_team.team_id)
        )
        lineup_entries = box.home_lineup if box.home_team.team_id == self.team_id else box.away_lineup

        lineup = []
        bench = []
        for bp in lineup_entries:
            if bp.slot_position in BENCH_SLOTS:
                bench.append(_to_roster_player(bp))
                continue
            if bp.name == "":
                lineup.append(LineupSlot(slot=bp.slot_position, player=None))
                continue
            lineup.append(LineupSlot(slot=bp.slot_position, player=_to_roster_player(bp)))

        logger.info(
            "Fetched ESPN team state: week=%s starters=%d bench=%d",
            current_week, len(lineup), len(bench),
        )
        return TeamState(week=current_week, lineup=lineup, bench=bench)
