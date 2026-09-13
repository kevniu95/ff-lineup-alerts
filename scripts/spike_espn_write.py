"""
Throwaway: verifies the real ESPN write-path (EspnClient.apply_swap) against
your actual live league before it's ever wired into the poller's automatic
AUTO-alert firing. See docs/build-plan.md step 3.

Finds the first real AUTO alert on your current lineup, prints exactly what
it would do, and asks for a typed confirmation before actually calling
ESPN's (undocumented) lineup-transaction endpoint -- this is a one-time
manual check, not a standing dry-run mode.

Run: uv run python scripts/spike_espn_write.py
"""
from dotenv import load_dotenv

from ff_lineup_alerts.decision_rules import AlertKind, run_all
from ff_lineup_alerts.espn_client import EspnClient


def main() -> None:
    load_dotenv()

    client = EspnClient.from_env()
    state = client.get_team_state()
    alerts = [a for a in run_all(state) if a.kind == AlertKind.AUTO]

    if not alerts:
        print(f"No AUTO alerts on week {state.week}'s lineup -- nothing to test right now.")
        return

    alert = alerts[0]
    starter_desc = alert.starter.name if alert.starter else "(empty slot)"
    print(f"Week {state.week}, slot {alert.slot}: {starter_desc} -> {alert.replacement.name}")
    print(f"Reason: {alert.reason}")
    print(f"Team: {client.team_link}")

    confirm = input("\nType 'yes' to actually execute this swap on ESPN: ").strip().lower()
    if confirm != "yes":
        print("Not confirmed -- nothing sent.")
        return

    result = client.apply_swap(state.week, alert.slot, alert.starter, alert.replacement)
    print(f"\nESPN response status: {result.get('status')}")
    print(result)


if __name__ == "__main__":
    main()
