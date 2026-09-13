"""
ESPN data spike -- see docs/build-plan.md step 1 / docs/scope.md Autonomy section.

Throwaway: pulls our own team's roster + lineup via `espn-api` and checks it
against the auto/suggest data-needs table in docs/scope.md:
  - bye week      -> gap in player.schedule's scoring-period keys
  - Out/IR/Susp.  -> player.injuryStatus (raw ESPN string)
  - empty slot    -> box_score lineup slot_position with no player
  - kickoff time  -> box_score lineup's per-player game_date/game_played

Run: .venv/bin/python scripts/spike_espn_client.py
"""
import os
from pathlib import Path

from espn_api.football import League


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def find_bye_week(schedule: dict, current_week: int, weeks_ahead: int = 4) -> int | None:
    """player.schedule is keyed by scoring-period string; a missing key = bye."""
    for week in range(current_week, current_week + weeks_ahead):
        if str(week) not in schedule:
            return week
    return None


def main() -> None:
    load_dotenv(Path(__file__).parent.parent / ".env")

    league = League(
        league_id=int(os.environ["ESPN_LEAGUE_ID"]),
        year=2026,
        espn_s2=os.environ["ESPN_S2"],
        swid=os.environ["ESPN_SWID"],
    )
    my_team = next(t for t in league.teams if t.team_id == int(os.environ["ESPN_TEAM_ID"]))
    print(f"Team: {my_team.team_name}  |  current week: {league.current_week}")

    print("\n--- Roster: status + bye check ---")
    for player in my_team.roster:
        bye = find_bye_week(player.schedule, league.current_week)
        print(
            f"{player.name:25s} status={player.injuryStatus!s:16s} "
            f"upcoming_bye={bye}"
        )

    print("\n--- Lineup slots + kickoff timing (from box score) ---")
    box = next(
        b for b in league.box_scores(league.current_week)
        if my_team.team_id in (b.home_team.team_id, b.away_team.team_id)
    )
    lineup = box.home_lineup if box.home_team.team_id == my_team.team_id else box.away_lineup
    for bp in lineup:
        empty = " <<< EMPTY SLOT" if bp.name == "" else ""
        print(
            f"slot={bp.slot_position:8s} player={bp.name:25s} "
            f"game_played={bp.game_played:3d} game_date={bp.game_date}{empty}"
        )


if __name__ == "__main__":
    main()
