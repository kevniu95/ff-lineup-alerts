"""
Unit tests for decision_rules.py against synthetic TeamStates -- no network
needed, unlike espn_client.py which is instead validated against live data
via scripts/spike_decision_rules_espn.py.
"""
from ff_lineup_alerts.decision_rules import (
    AlertKind,
    check_better_projected_bench,
    check_empty_slot,
    check_questionable_doubtful,
    check_starter_on_bye,
    check_starter_out,
    run_all,
)
from ff_lineup_alerts.league import LineupSlot, RosterPlayer, TeamState

FLEX_SLOTS = ["WR", "RB/WR", "WR/TE", "RB/WR/TE", "BE"]


def make_player(
    name,
    status="ACTIVE",
    on_bye=False,
    has_played=False,
    proj=0.0,
    eligible_slots=None,
):
    return RosterPlayer(
        name=name,
        status=status,
        on_bye=on_bye,
        has_played=has_played,
        projection=proj,
        eligible_slots=eligible_slots or FLEX_SLOTS,
    )


def make_state(lineup, bench, week=3):
    return TeamState(week=week, lineup=lineup, bench=bench)


def test_starter_on_bye_fires_with_eligible_replacement():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Byeguy", on_bye=True, proj=10))],
        bench=[make_player("Bench1", proj=5)],
    )
    alerts = check_starter_on_bye(state)
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.AUTO
    assert alerts[0].starter.name == "Byeguy"
    assert alerts[0].replacement.name == "Bench1"


def test_starter_on_bye_does_not_fire_without_eligible_replacement():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Byeguy", on_bye=True, proj=10))],
        bench=[make_player("WrongSlot", proj=5, eligible_slots=["QB", "BE"])],
    )
    assert check_starter_on_bye(state) == []


def test_starter_on_bye_ignores_bench_with_zero_projection():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Byeguy", on_bye=True, proj=10))],
        bench=[make_player("ZeroProj", proj=0)],
    )
    assert check_starter_on_bye(state) == []


def test_starter_out_fires_for_out_ir_suspended():
    for status in ("OUT", "INJURY_RESERVE", "SUSPENSION"):
        state = make_state(
            lineup=[LineupSlot("WR", make_player("Hurtguy", status=status, proj=10))],
            bench=[make_player("Bench1", proj=5)],
        )
        alerts = check_starter_out(state)
        assert len(alerts) == 1, f"expected an alert for status={status}"
        assert alerts[0].kind == AlertKind.AUTO


def test_starter_out_suppressed_once_starter_has_played():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("AJBrown", status="INJURY_RESERVE", proj=12, has_played=True))],
        bench=[make_player("Bench1", proj=5)],
    )
    assert check_starter_out(state) == []


def test_empty_slot_fires_even_with_no_eligible_replacement():
    state = make_state(
        lineup=[LineupSlot("TE", None)],
        bench=[make_player("WrongSlot", proj=5, eligible_slots=["QB", "BE"])],
    )
    alerts = check_empty_slot(state)
    assert len(alerts) == 1
    assert alerts[0].starter is None
    assert alerts[0].replacement is None


def test_questionable_doubtful_fires_as_suggest():
    for status in ("QUESTIONABLE", "DOUBTFUL"):
        state = make_state(
            lineup=[LineupSlot("WR", make_player("Iffyguy", status=status, proj=10))],
            bench=[make_player("Bench1", proj=5)],
        )
        alerts = check_questionable_doubtful(state)
        assert len(alerts) == 1
        assert alerts[0].kind == AlertKind.SUGGEST


def test_questionable_doubtful_suppressed_once_starter_has_played():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Iffyguy", status="QUESTIONABLE", proj=10, has_played=True))],
        bench=[make_player("Bench1", proj=5)],
    )
    assert check_questionable_doubtful(state) == []


def test_better_projected_bench_fires_when_margin_cleared():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("LowProj", proj=5))],
        bench=[make_player("HighProj", proj=15)],
    )
    alerts = check_better_projected_bench(state)
    assert len(alerts) == 1
    assert alerts[0].kind == AlertKind.SUGGEST
    assert alerts[0].replacement.name == "HighProj"


def test_better_projected_bench_does_not_fire_within_margin():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Starter", proj=10))],
        bench=[make_player("SlightlyBetter", proj=11)],
    )
    assert check_better_projected_bench(state) == []


def test_better_projected_bench_suppressed_once_starter_has_played():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Starter", proj=5, has_played=True))],
        bench=[make_player("HighProj", proj=15)],
    )
    assert check_better_projected_bench(state) == []


def test_better_projected_bench_uses_third_party_projection_when_given():
    state = make_state(
        lineup=[LineupSlot("WR", make_player("Starter", proj=5))],
        bench=[make_player("HighProj", proj=15)],
    )

    # ESPN says HighProj clears the margin, but the independent source says
    # it doesn't -- should suppress the alert.
    def third_party(name):
        return {"Starter": 5.0, "HighProj": 6.0}.get(name)

    assert check_better_projected_bench(state, third_party_projection=third_party) == []


def test_run_all_aggregates_every_rule():
    state = make_state(
        lineup=[
            LineupSlot("WR", make_player("ByeGuy", on_bye=True, proj=10)),
            LineupSlot("TE", None),
        ],
        bench=[make_player("Bench1", proj=15)],
    )
    alerts = run_all(state)
    rules_fired = {a.rule for a in alerts}
    assert "starter_on_bye" in rules_fired
    assert "empty_slot" in rules_fired
    assert "better_projected_bench" in rules_fired
