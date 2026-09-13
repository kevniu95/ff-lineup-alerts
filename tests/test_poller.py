"""
Unit tests for poller.py's pure logic: message formatting and league
configuration gating. run_league_check itself hits real league APIs, so it's
validated by hand via --test espn/sleeper/check instead (see README.md).
"""
from ff_lineup_alerts import poller
from ff_lineup_alerts.decision_rules import Alert, AlertKind


def make_alert(kind, rule="some_rule", slot="WR", starter_name="Starter", replacement_name="Replacement"):
    starter = type("P", (), {"name": starter_name})()
    replacement = type("P", (), {"name": replacement_name})()
    return Alert(kind=kind, rule=rule, slot=slot, starter=starter, replacement=replacement, reason="because")


def test_format_alerts_message_returns_none_when_no_alerts():
    assert poller.format_alerts_message("ESPN", 3, []) is None


def test_format_alerts_message_labels_league_and_week():
    message = poller.format_alerts_message("ESPN", 3, [make_alert(AlertKind.AUTO)])
    assert message.startswith("[ESPN] Week 3 lineup check")


def test_format_alerts_message_separates_auto_and_suggest():
    alerts = [make_alert(AlertKind.AUTO, rule="starter_out"), make_alert(AlertKind.SUGGEST, rule="questionable_doubtful")]
    message = poller.format_alerts_message("Sleeper", 1, alerts)
    assert "Auto-fix candidates" in message
    assert "Suggested" in message
    assert message.index("Auto-fix candidates") < message.index("Suggested")


def test_configured_leagues_only_includes_leagues_with_env_set(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "123")
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    leagues = poller.configured_leagues()
    assert [lc.name for lc in leagues] == ["ESPN"]


def test_configured_leagues_includes_both_when_both_set(monkeypatch):
    monkeypatch.setenv("ESPN_LEAGUE_ID", "123")
    monkeypatch.setenv("SLEEPER_LEAGUE_ID", "456")
    leagues = poller.configured_leagues()
    assert {lc.name for lc in leagues} == {"ESPN", "Sleeper"}


def test_configured_leagues_empty_when_none_set(monkeypatch):
    monkeypatch.delenv("ESPN_LEAGUE_ID", raising=False)
    monkeypatch.delenv("SLEEPER_LEAGUE_ID", raising=False)
    assert poller.configured_leagues() == []
