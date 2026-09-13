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

import requests
from espn_api.football import League
from espn_api.football.constant import POSITION_MAP
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague

from ff_lineup_alerts.league import LeagueAuthError, LineupSlot, RosterPlayer, TeamState

logger = logging.getLogger("espn_client")

BENCH_SLOTS = {"BE", "IR"}
BENCH_SLOT = "BE"

# ESPN's own injuryStatus strings already match league.py's canonical
# vocabulary for player status ("ACTIVE", "OUT", "QUESTIONABLE", etc.) --
# the one known exception is D/ST entries, which ESPN reports as "NORMAL"
# rather than "ACTIVE".
STATUS_MAP = {"NORMAL": "ACTIVE"}

# espn_api's own POSITION_MAP is {int: label} plus a handful of {label: int}
# shortcuts that don't cover every slot (e.g. "BE"/"IR"/compound flex names
# are missing on the label->id side) -- build a complete reverse mapping
# ourselves from just the int keys instead of relying on those extras.
SLOT_TO_ID = {v: k for k, v in POSITION_MAP.items() if isinstance(k, int)}

# Undocumented, reverse-engineered from ESPN's own web app traffic -- see
# docs/scope.md's write-path notes. Could change or break without notice.
TRANSACTIONS_URL = (
    "https://lm-api-writes.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}"
    "/segments/0/leagues/{league_id}/transactions/"
)


def _normalize_status(raw_status: str) -> str:
    return STATUS_MAP.get(raw_status, raw_status)


def _to_roster_player(bp) -> RosterPlayer:
    return RosterPlayer(
        name=bp.name,
        status=_normalize_status(bp.injuryStatus),
        on_bye=bp.on_bye_week,
        # espn-api's game_played is really a binary "kickoff + 3hrs has passed"
        # flag despite the 0-100 "percent of game played" naming.
        has_played=bp.game_played >= 100,
        projection=bp.projected_points,
        eligible_slots=list(bp.eligibleSlots),
        player_id=str(bp.playerId),
    )


class EspnClient:
    def __init__(self, league_id: int, year: int, espn_s2: str, swid: str, team_id: int):
        # espn_api's League() constructor eagerly fetches the league (auth
        # happens right here, not lazily on first real call).
        try:
            self.league = League(league_id=league_id, year=year, espn_s2=espn_s2, swid=swid)
        except ESPNAccessDenied as e:
            raise LeagueAuthError(
                f"ESPN rejected credentials for league {league_id} -- ESPN_S2/ESPN_SWID "
                f"have likely expired and need refreshing from a browser session: {e}"
            ) from e
        except ESPNInvalidLeague as e:
            raise LeagueAuthError(f"ESPN league {league_id} not found -- check ESPN_LEAGUE_ID: {e}") from e
        self.league_id = league_id
        self.year = year
        self.espn_s2 = espn_s2
        self.swid = swid
        self.team_id = team_id

    @property
    def team_link(self) -> str:
        return f"https://fantasy.espn.com/football/team?leagueId={self.league_id}&teamId={self.team_id}"

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
            lineup.append(LineupSlot(slot=bp.slot_position, player=_to_roster_player(bp)))

        # ESPN doesn't emit a placeholder entry for a starting slot with no
        # player assigned -- box_scores() just returns fewer lineup entries
        # than the league's configured starting-slot counts. Diff actual
        # counts per slot label against league.settings.position_slot_counts
        # to find those and append the missing (empty) slots ourselves.
        starting_slot_counts = {
            slot: count for slot, count in self.league.settings.position_slot_counts.items()
            if slot and slot not in BENCH_SLOTS and count
        }
        filled_counts: dict[str, int] = {}
        for entry in lineup:
            filled_counts[entry.slot] = filled_counts.get(entry.slot, 0) + 1
        for slot_label, expected_count in starting_slot_counts.items():
            missing = expected_count - filled_counts.get(slot_label, 0)
            lineup.extend(LineupSlot(slot=slot_label, player=None) for _ in range(missing))

        logger.info(
            "Fetched ESPN team state: week=%s starters=%d bench=%d",
            current_week, len(lineup), len(bench),
        )
        return TeamState(week=current_week, lineup=lineup, bench=bench)

    def apply_swap(
        self,
        week: int,
        slot: str,
        starter: RosterPlayer | None,
        replacement: RosterPlayer,
    ) -> dict:
        """
        Bench `starter` (if any -- an empty-slot alert has none) and start
        `replacement` in `slot`, via ESPN's undocumented lineup-transaction
        endpoint (see TRANSACTIONS_URL). scoringPeriodId must be the league's
        *current* week -- ESPN rejects writes for any other week.
        """
        slot_id = SLOT_TO_ID[slot]
        bench_id = SLOT_TO_ID[BENCH_SLOT]

        items = []
        if starter is not None:
            items.append({
                "playerId": int(starter.player_id),
                "type": "LINEUP",
                "fromLineupSlotId": slot_id,
                "toLineupSlotId": bench_id,
            })
        items.append({
            "playerId": int(replacement.player_id),
            "type": "LINEUP",
            "fromLineupSlotId": bench_id,
            "toLineupSlotId": slot_id,
        })

        body = {
            "isLeagueManager": False,
            "teamId": self.team_id,
            "type": "ROSTER",
            "memberId": self.swid,
            "scoringPeriodId": week,
            "executionType": "EXECUTE",
            "items": items,
        }
        url = TRANSACTIONS_URL.format(year=self.year, league_id=self.league_id)
        # memberId (SWID) is authentication, not something to log even at
        # DEBUG -- log everything else about the request instead.
        logger.debug(
            "ESPN transaction request: url=%s teamId=%s scoringPeriodId=%s items=%s",
            url, self.team_id, week, items,
        )
        resp = requests.post(
            url,
            json=body,
            cookies={"SWID": self.swid, "espn_s2": self.espn_s2},
        )
        resp.raise_for_status()
        result = resp.json()
        logger.debug("ESPN transaction response: %s", result)
        logger.info(
            "Applied ESPN swap: slot=%s starter=%s replacement=%s status=%s",
            slot, starter.name if starter else None, replacement.name, result.get("status"),
        )
        return result
