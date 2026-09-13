# ff-lineup-alerts

Push-based lineup alerts for ESPN and Sleeper fantasy football leagues: fixed
weekly check-ins, auto-fix for obvious problems (bye weeks, OUT starters),
tap-to-approve suggestions for judgment calls, and open-ended Q&A via the same
Telegram thread.

See [docs/scope.md](docs/scope.md) for the full scoping doc and
[docs/build-plan.md](docs/build-plan.md) for what's built vs. still planned.

## Running tests

```
uv run pytest
```

Covers `decision_rules.py` (pure logic, no network) against synthetic
lineups. `espn_client.py` needs live ESPN cookies, so it's instead
validated by hand against a real league — see `scripts/spike_decision_rules_espn.py`.
