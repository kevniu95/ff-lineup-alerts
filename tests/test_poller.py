"""
Unit tests for poller.py's pure logic: message formatting, auto-alert
execution, and league configuration gating. run_league_check itself hits
real league APIs, so it's validated by hand via --test espn/sleeper/check
instead (see README.md).
"""
from ff_lineup_alerts import poller
from ff_lineup_alerts.decision_rules import Alert, AlertKind
from ff_lineup_alerts.league import LeagueAuthError
from ff_lineup_alerts.poller import AlertOutcome, LeagueConfig


def make_alert(kind, rule="some_rule", slot="WR", starter_name="Starter", replacement_name="Replacement"):
    starter = type("P", (), {"name": starter_name})()
    replacement = type("P", (), {"name": replacement_name})()
    return Alert(kind=kind, rule=rule, slot=slot, starter=starter, replacement=replacement, reason="because")


def test_format_alerts_message_returns_none_when_no_outcomes():
    assert poller.format_alerts_message("ESPN", 3, [], "https://example.com/team") is None


def test_format_alerts_message_labels_league_and_week():
    outcomes = [AlertOutcome(alert=make_alert(AlertKind.AUTO), applied=True)]
    message = poller.format_alerts_message("ESPN", 3, outcomes, "https://example.com/team")
    assert message.startswith("[ESPN] Week 3")


def test_format_alerts_message_separates_applied_unsupported_and_suggest():
    outcomes = [
        AlertOutcome(alert=make_alert(AlertKind.AUTO, rule="starter_out"), applied=True),
        AlertOutcome(alert=make_alert(AlertKind.AUTO, rule="starter_on_bye"), applied=False),
        AlertOutcome(alert=make_alert(AlertKind.SUGGEST, rule="questionable_doubtful"), applied=False),
    ]
    message = poller.format_alerts_message("Sleeper", 1, outcomes, "https://example.com/team")
    assert "Automated Fixes" in message
    assert "Applied:" in message
    assert "Not supported (write-path not built for this platform):" in message
    assert "Suggested Fixes" in message
    assert message.index("Applied:") < message.index("Not supported") < message.index("Suggested Fixes")


def test_format_alerts_message_reports_failed_auto_alert():
    outcomes = [AlertOutcome(alert=make_alert(AlertKind.AUTO), applied=False, error="boom")]
    message = poller.format_alerts_message("ESPN", 3, outcomes, "https://example.com/team")
    assert "Failed to apply:" in message
    assert "boom" in message


def test_format_alerts_message_numbers_multiple_alerts_in_a_section():
    outcomes = [
        AlertOutcome(alert=make_alert(AlertKind.SUGGEST, starter_name="A"), applied=False),
        AlertOutcome(alert=make_alert(AlertKind.SUGGEST, starter_name="B"), applied=False),
    ]
    message = poller.format_alerts_message("ESPN", 3, outcomes, "https://example.com/team")
    assert "1. WR: A ->" in message
    assert "2. WR: B ->" in message


def test_format_alerts_message_omits_automated_fixes_section_when_only_suggestions():
    outcomes = [AlertOutcome(alert=make_alert(AlertKind.SUGGEST), applied=False)]
    message = poller.format_alerts_message("ESPN", 3, outcomes, "https://example.com/team")
    assert "Automated Fixes" not in message


def test_format_alerts_message_includes_team_link():
    outcomes = [AlertOutcome(alert=make_alert(AlertKind.AUTO), applied=True)]
    message = poller.format_alerts_message("ESPN", 3, outcomes, "https://example.com/team")
    assert message.endswith("https://example.com/team")


class _ClientWithApplySwap:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    def apply_swap(self, week, slot, starter, replacement):
        self.calls.append((week, slot, starter, replacement))
        if self.should_fail:
            raise RuntimeError("boom")


class _ClientWithoutApplySwap:
    pass


def test_apply_auto_alerts_executes_auto_alerts_when_supported():
    client = _ClientWithApplySwap()
    alert = make_alert(AlertKind.AUTO)
    outcomes = poller._apply_auto_alerts(client, 3, [alert])
    assert outcomes == [AlertOutcome(alert=alert, applied=True)]
    assert client.calls == [(3, alert.slot, alert.starter, alert.replacement)]


def test_apply_auto_alerts_skips_suggest_alerts():
    client = _ClientWithApplySwap()
    alert = make_alert(AlertKind.SUGGEST)
    outcomes = poller._apply_auto_alerts(client, 3, [alert])
    assert outcomes == [AlertOutcome(alert=alert, applied=False)]
    assert client.calls == []


def test_apply_auto_alerts_marks_unsupported_when_client_lacks_apply_swap():
    client = _ClientWithoutApplySwap()
    alert = make_alert(AlertKind.AUTO)
    outcomes = poller._apply_auto_alerts(client, 3, [alert])
    assert outcomes == [AlertOutcome(alert=alert, applied=False, error=None)]


def test_apply_auto_alerts_captures_error_on_failure():
    client = _ClientWithApplySwap(should_fail=True)
    alert = make_alert(AlertKind.AUTO)
    outcomes = poller._apply_auto_alerts(client, 3, [alert])
    assert len(outcomes) == 1
    assert outcomes[0].applied is False
    assert outcomes[0].error == "boom"


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


def test_run_league_check_reports_auth_error_as_message():
    def build_client():
        raise LeagueAuthError("ESPN_S2/ESPN_SWID have likely expired")

    league = LeagueConfig(name="ESPN", build_client=build_client, required_env="ESPN_LEAGUE_ID")
    message = poller.run_league_check(league)
    assert message == "[ESPN] Could not connect: ESPN_S2/ESPN_SWID have likely expired"
