"""
Throwaway: runs the real decision_rules.ALL_RULES against a live Sleeper team
state, same as scripts/spike_decision_rules_espn.py does for ESPN -- confirms
sleeper_client.py's normalization actually lines up with decision_rules.py's
expectations against a real league.

Run: .venv/bin/python scripts/spike_decision_rules_sleeper.py
"""
from pathlib import Path

from ff_lineup_alerts.decision_rules import run_all
from ff_lineup_alerts.sleeper_client import SleeperClient


def load_dotenv(path: Path) -> None:
    import os
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")

    client = SleeperClient.from_env()
    state = client.get_team_state()

    print(f"Week {state.week}")
    print("\n--- Lineup ---")
    for slot in state.lineup:
        if slot.player is None:
            print(f"slot={slot.slot:10s} <<< EMPTY")
        else:
            print(
                f"slot={slot.slot:10s} {slot.player.name:25s} status={slot.player.status:16s} "
                f"bye={slot.player.on_bye} played={slot.player.has_played} proj={slot.player.projection}"
            )

    print("\n--- Bench ---")
    for b in state.bench:
        print(
            f"{b.name:25s} status={b.status:16s} bye={b.on_bye} played={b.has_played} "
            f"proj={b.projection} eligible={b.eligible_slots}"
        )

    print("\n--- Alerts ---")
    alerts = run_all(state)
    if not alerts:
        print("(none)")
    for a in alerts:
        starter_name = a.starter.name if a.starter else "(empty slot)"
        replacement_name = a.replacement.name if a.replacement else "(no eligible replacement)"
        print(f"[{a.kind.value:7s}] {a.rule:24s} slot={a.slot:10s} {starter_name} -> {replacement_name} | {a.reason}")


if __name__ == "__main__":
    main()
