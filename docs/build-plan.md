# Build Plan

Order of work. See [scope.md](scope.md) for the what/why — this is just the
sequence, each step should produce something concretely testable before
moving to the next.

## Done

- **Season schedule generation** (`scripts/generate_schedule.py`,
  `data/schedule.json`)
  - Source: ESPN's public scoreboard API (no auth needed), pulled per-week.
  - Checkpoints are derived, not hand-picked: bucket a week's real kickoff
    times (new bucket if the gap exceeds 3hrs), checkpoint = bucket's
    earliest kickoff − 15min.
    - Handles holiday weeks (Thanksgiving, Christmas) and international
      games correctly with no day-of-week special-casing.
  - All timestamps stored in UTC; local-time is a display-time concern only.
  - Known gap: late-season flex-scheduled games (Week 17/18) don't have real
    times yet — mitigated by re-running the script periodically.
  - Dropped the standing "Wed waiver/injury summary" check — left as a TODO
    for a separate waiver-wire alert to take its place later.

- **Poller cron skeleton** (`poller.py`, `railway.json`)
  - Deployed as a Railway cron-scheduled service; cron schedule is set in
    Railway's dashboard UI (not config-as-code), to avoid ambiguity over
    which source of truth wins if both are ever edited.
  - Confirmed real end-to-end Telegram delivery, and both a forced fire and
    no-fire case via `--test`.
  - Checkpoint matching is forward-only (`0 <= at - now < CHECK_WINDOW`), so
    it fires exactly once per checkpoint with no misses or duplicates, as
    long as `CHECK_WINDOW` matches the configured cron interval.

- **LLM connectivity spike** (`scripts/spike_llm_claude.py`,
  `scripts/spike_llm_openai.py`)
  - Confirmed our own code can call an LLM API programmatically with its own
    API key/billing account (separate from the interactive Claude.ai/Claude
    Code subscription) — tested against both Claude and OpenAI.
  - Going with **Claude** (Sonnet 5) for step 5's actual implementation.
  - Real numbers at expected volume (a handful of calls/day/user, small
    roster/matchup context): well under $1-5/month regardless of model
    tier chosen — cost is not a deciding factor. Anthropic Console has a
    separate Usage/Cost dashboard (distinct from the Claude.ai subscription
    billing) if spend ever needs checking.
  - Considered logging per-call token usage/cost for ongoing tracking, but
    skipped it — Railway retains logs across restarts, but only for a
    plan-tier-limited window (3-30 days), and at this volume the Console
    dashboard is simpler and sufficient. Revisit only if call volume grows
    enough to matter.

- **ESPN data client + decision rules** (`src/ff_lineup_alerts/espn_client.py`,
  `src/ff_lineup_alerts/decision_rules.py`)
  - ESPN goes first (Sleeper deferred): `espn-api`'s box-score lineup
    (`BoxPlayer`, one entry per roster spot including bench/IR) already
    carries week-specific `projected_points`, `on_bye_week`, and
    `injuryStatus` directly — no client-side bye-week diffing or a second
    projections endpoint needed, unlike Sleeper (see scope.md's Data
    sources).
  - All six rules from scope.md's Autonomy table implemented and verified
    against synthetic `TeamState`s: starter-on-bye, starter Out/IR/Suspended,
    empty slot, questionable/doubtful, and better-projected-on-bench (the
    last with an optional `third_party_projection` callable hook, unwired,
    for the independent-projection cross-check from scope.md's open
    questions).
  - Real-data run (`scripts/spike_decision_rules_espn.py`) confirms the
    client pulls correct live projections/status/bye against the actual
    league; no rules fired, which is correct for the current (clean) lineup
    state — the rule logic itself is what the synthetic-state run verifies.
  - Not yet exercised against a real bye/injury/questionable case (none
    present in the live league right now) — revisit once one occurs
    naturally, or consider a recorded-fixture test if that wait is too long.

- **League interface + Sleeper client** (`src/ff_lineup_alerts/league.py`,
  `src/ff_lineup_alerts/sleeper_client.py`)
  - Built earlier than originally planned: normalizing Sleeper's raw
    `injury_status` strings (`"Out"`, `"IR"`, `"Sus"`, plus edge values like
    `PUP`/`NA`/`DNR`/`COV`) into something `decision_rules.py` could compare
    against ESPN's (`"OUT"`, `"INJURY_RESERVE"`, ...) needed a shared
    canonical vocabulary regardless of whether the poller looped over
    multiple leagues yet — so `TeamState`/`LineupSlot`/`RosterPlayer` and a
    `LeagueClient` protocol moved out of `espn_client.py` into `league.py`,
    and both clients now normalize into it.
  - `sleeper_client.py` covers bye/status/projections/lineup/eligibility and
    a real `has_played` signal (Sleeper's schedule endpoint has a per-game
    `status` field — `"pre_game"` vs. anything else — cleaner than the
    date-only approximation originally expected to be needed).
  - PUP/NA/DNR/COV → OUT-equivalent status bucketing and the flex-slot
    eligibility map (FLEX/SUPER_FLEX/WRRB_FLEX/REC_FLEX) were reviewed and
    confirmed good enough as-is — no longer TODOs.
  - Player-cache path is Volume-aware: reads `RAILWAY_VOLUME_MOUNT_PATH`
    (which Railway sets automatically once a Volume is attached to the
    poller service, whatever mount path is chosen) and falls back to a
    local `data/cache/` dir otherwise; a sidecar timestamp file gates
    re-fetching the 14MB dump to once/24h. See scope.md's open questions —
    the only remaining step is creating + attaching the Volume in Railway's
    dashboard; no further code changes needed.
  - Verified against real Sleeper data via
    `scripts/spike_decision_rules_sleeper.py` (mirrors the ESPN spike).

## Plan

1. **Data clients**
   - Sleeper client pulling real roster/matchup/injury data (ESPN's is done,
     above). Sleeper's known extra complexity: bye weeks and projections come
     from separate undocumented endpoints, and the 14MB player dump needs a
     Railway Volume cache (see scope.md's open questions).
2. **Decision rules**
   - ESPN-only implementation is done (above). Extend to Sleeper once its
     client exists, or ship ESPN-only first if that unblocks value sooner.
   - Wire alerts into the poller: auto-fix sends an FYI; suggest-only sends
     tap buttons over the same Telegram bot.
3. **Write-path**
   - Implement the "execute this swap" library function itself (the shared
     core-library action from scope.md's architecture) against ESPN/Sleeper's
     APIs.
   - Test it standalone/scripted — no Telegram involved yet.
     - Dry-run first.
     - Then a low-stakes roster.
     - Only then trust it on a league that actually matters.
4. **Interactive Telegram**
   - Stand up the webhook handler as a second, always-on Railway service —
     deferred from the deploy-skeleton work since there was nothing for it
     to receive until buttons/free-text exist to handle.
   - Button taps: wire up real handling for Approve/Dismiss/Show alternatives.
     - A tap just calls the already-tested execute-swap function from (3).
     - This step is only Telegram-side plumbing (receiving the tap, calling
       into it, replying) — not new write logic.
     - Test: deterministic execution end-to-end.
   - Free-text: wire up LLM routing with live roster/matchup context,
     building on the connectivity spike.
     - Test conversationally — ask it real lineup questions.
     - Confirm the context it's reasoning over is actually current/correct.
