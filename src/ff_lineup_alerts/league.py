"""
Platform-neutral types shared by every league client (ESPN, Sleeper, and
whatever comes next), plus the LeagueClient protocol poller.py programs
against so it doesn't need to know which platform a given league is on.

Canonical `RosterPlayer.status` values -- every client normalizes its raw
platform status into these before constructing a RosterPlayer, so
decision_rules.py never has to know a platform's own vocabulary:
    "ACTIVE", "OUT", "INJURY_RESERVE", "SUSPENSION", "QUESTIONABLE", "DOUBTFUL"
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class RosterPlayer:
    name: str
    status: str  # one of the canonical values above
    on_bye: bool
    has_played: bool  # this week's game is over (or well underway) for this player
    projection: float
    eligible_slots: list[str]  # this league's own slot labels the player qualifies for
    player_id: str | None = None  # platform-native id, needed to actually execute a swap


@dataclass
class LineupSlot:
    slot: str
    player: RosterPlayer | None  # None means the slot is empty


@dataclass
class TeamState:
    week: int
    lineup: list[LineupSlot]
    bench: list[RosterPlayer]


class LeagueClient(Protocol):
    def get_team_state(self) -> TeamState: ...


class LeagueAuthError(Exception):
    """
    Raised by a client's construction (or first real request) when the
    platform rejects its credentials -- e.g. ESPN's espn_s2/SWID cookies
    have expired. Platform-neutral so poller.py can catch one thing
    regardless of which client raised it, per docs/scope.md's "How ESPN
    cookie refresh gets triggered/reminded" open question.
    """
