"""
Decision rules from docs/scope.md's Autonomy section, evaluated against a
TeamState (see espn_client.py). ESPN-only for now — see scope.md for why
ESPN goes first.

Each rule returns a list of Alert. Auto-fix alerts are informational (the
swap already happened, or would happen, by the time this fires); suggest
alerts always carry the candidate replacement for a tap to approve.
"""
import logging
from dataclasses import dataclass
from enum import Enum

from ff_lineup_alerts.espn_client import LineupSlot, RosterPlayer, TeamState

logger = logging.getLogger("decision_rules")

OUT_STATUSES = {"OUT", "INJURY_RESERVE", "SUSPENSION"}
QUESTIONABLE_STATUSES = {"QUESTIONABLE", "DOUBTFUL"}

# How much higher a bench player's projection must be to count as "meaningfully
# higher" for the suggest-only rule. Kept as a plain constant for now; revisit
# if it needs to be tunable per-user.
PROJECTION_MARGIN = 2.0


class AlertKind(Enum):
    AUTO = "auto"
    SUGGEST = "suggest"


@dataclass
class Alert:
    kind: AlertKind
    rule: str
    slot: str
    starter: RosterPlayer | None
    replacement: RosterPlayer | None
    reason: str


def _eligible_bench_candidates(slot: LineupSlot, bench: list[RosterPlayer]) -> list[RosterPlayer]:
    return [
        b for b in bench
        if slot.slot in b.eligible_slots and (b.projection or 0) > 0
    ]


def _best_candidate(candidates: list[RosterPlayer]) -> RosterPlayer | None:
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.projection or 0)


def check_starter_on_bye(state: TeamState) -> list[Alert]:
    alerts = []
    for slot in state.lineup:
        if slot.player is None or not slot.player.on_bye:
            continue
        candidate = _best_candidate(_eligible_bench_candidates(slot, state.bench))
        if candidate is None:
            continue
        alerts.append(Alert(
            kind=AlertKind.AUTO,
            rule="starter_on_bye",
            slot=slot.slot,
            starter=slot.player,
            replacement=candidate,
            reason=f"{slot.player.name} is on bye week {state.week}",
        ))
    return alerts


def check_starter_out(state: TeamState) -> list[Alert]:
    alerts = []
    for slot in state.lineup:
        if slot.player is None or slot.player.status not in OUT_STATUSES:
            continue
        if slot.player.has_played:
            # e.g. AJ Brown goes to IR after his own Sunday game -- stale by
            # next week's checkpoint if he's still listed, but not this week:
            # his slot is already locked and there's nothing to swap.
            continue
        candidate = _best_candidate(_eligible_bench_candidates(slot, state.bench))
        if candidate is None:
            continue
        alerts.append(Alert(
            kind=AlertKind.AUTO,
            rule="starter_out",
            slot=slot.slot,
            starter=slot.player,
            replacement=candidate,
            reason=f"{slot.player.name} status is {slot.player.status}",
        ))
    return alerts


def check_empty_slot(state: TeamState) -> list[Alert]:
    alerts = []
    for slot in state.lineup:
        if slot.player is not None:
            continue
        candidate = _best_candidate(_eligible_bench_candidates(slot, state.bench))
        alerts.append(Alert(
            kind=AlertKind.AUTO,
            rule="empty_slot",
            slot=slot.slot,
            starter=None,
            replacement=candidate,
            reason="Starting slot has no player assigned",
        ))
    return alerts


def check_questionable_doubtful(state: TeamState) -> list[Alert]:
    alerts = []
    for slot in state.lineup:
        if slot.player is None or slot.player.status not in QUESTIONABLE_STATUSES:
            continue
        if slot.player.has_played:
            continue
        candidate = _best_candidate(_eligible_bench_candidates(slot, state.bench))
        alerts.append(Alert(
            kind=AlertKind.SUGGEST,
            rule="questionable_doubtful",
            slot=slot.slot,
            starter=slot.player,
            replacement=candidate,
            reason=f"{slot.player.name} status is {slot.player.status}",
        ))
    return alerts


def check_better_projected_bench(
    state: TeamState,
    third_party_projection=None,
) -> list[Alert]:
    """
    third_party_projection: optional callable(player_name: str) -> float | None,
    for the independent-projection cross-check flagged as an open question in
    scope.md. When given, a candidate must also clear the margin on this
    source, not just ESPN's own projection, before the alert fires. Not yet
    wired up to a real provider.
    """
    alerts = []
    for slot in state.lineup:
        if slot.player is None or slot.player.status in OUT_STATUSES:
            continue
        if slot.player.has_played:
            # starter's already locked in his score for the week -- ESPN
            # won't allow the swap even if the bench candidate looks better.
            continue
        starter_proj = slot.player.projection or 0
        candidate = _best_candidate(_eligible_bench_candidates(slot, state.bench))
        if candidate is None or (candidate.projection or 0) < starter_proj + PROJECTION_MARGIN:
            continue
        if third_party_projection is not None:
            third_party_candidate = third_party_projection(candidate.name)
            third_party_starter = third_party_projection(slot.player.name)
            if third_party_candidate is None or third_party_starter is None:
                continue
            if third_party_candidate < third_party_starter + PROJECTION_MARGIN:
                continue
        alerts.append(Alert(
            kind=AlertKind.SUGGEST,
            rule="better_projected_bench",
            slot=slot.slot,
            starter=slot.player,
            replacement=candidate,
            reason=(
                f"{candidate.name} projected {candidate.projection:.1f} vs "
                f"{slot.player.name} projected {starter_proj:.1f}"
            ),
        ))
    return alerts


ALL_RULES = [
    check_starter_on_bye,
    check_starter_out,
    check_empty_slot,
    check_questionable_doubtful,
    check_better_projected_bench,
]


def run_all(state: TeamState) -> list[Alert]:
    alerts = []
    for rule in ALL_RULES:
        found = rule(state)
        if found:
            logger.info("%s: %d alert(s)", rule.__name__, len(found))
        alerts.extend(found)
    return alerts
