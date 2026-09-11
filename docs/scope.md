# Fantasy Lineup Alerts — Scope

## Goal
A push-based system that watches my ESPN and Sleeper fantasy football lineups each
week, alerts me to problems (bye weeks, injuries, better bench options), auto-fixes
the obvious cases, and lets me ask open-ended lineup questions from my phone.

## Interaction model
- Single channel per league: a Telegram bot (separate bot/thread per league — ESPN
  and Sleeper are kept independent so a conflict, e.g. the same bye-week player
  rostered in both, never gets muddled into one thread).
- Each alert is a message with inline tap buttons (Approve / Dismiss / Show
  alternatives) for the suggested action.
- The same chat also accepts free-text questions ("who should I flex, X or Y?"),
  which get routed to an LLM call with that league's live roster/matchup data as
  context and answered conversationally.
- Button taps are deterministic (no LLM in the loop) — they just execute the
  suggested roster action directly.

## Autonomy — what auto-executes vs. what waits for a tap
**Auto-fix (no confirmation needed, FYI notification after):**
- Starter is on a bye week AND a bench player is active at that same eligible slot
  with a nonzero projection.
- Starter is officially "OUT"/inactive AND a bench player is active at that same
  eligible slot with a nonzero projection.

**Suggest only (requires a tap, never auto-applied):**
- Anything comparing two active/playing players by projection alone.
- Questionable / doubtful statuses — surfaced as info, not auto-swapped.
- Any swap that would need a slot the bench player isn't actually eligible for
  (auto-fix logic must check eligibility, not just "any bench player").

## Trigger schedule
- Season has a fixed number of weeks and each week has fixed game days, so checks
  run on a **fixed, precomputed schedule** rather than continuous polling — no need
  for the poller to run more than ~5x/week.
- Rough per-week cadence (final list to be generated programmatically from the
  season's start date, not hand-maintained):
  - Wed — waiver/injury summary (low urgency)
  - Thu ~4pm — pre-TNF lock check
  - Sat ~8pm — Sunday injury reports starting to trickle in
  - Sun ~9am — injury re-check
  - Sun ~11:15am — final pre-lock check (highest priority)
- No Monday checks (no lineup decisions pending).
- A check only produces a notification when something is actually warranted —
  silent otherwise.

## Data sources
- **Sleeper**: public REST API, no auth needed.
- **ESPN**: unofficial API, requires `espn_s2` + `SWID` cookies from a logged-in
  browser session. These can expire; acceptable to re-grab manually/periodically.
  Need a way to detect "auth looks broken" and surface that instead of failing
  silently.

## Architecture (rough)
Two Railway services, not one always-on monolith:
1. **Poller** — Railway cron-scheduled service. Wakes at each fixed timestamp,
   pulls rosters/matchups/injury data from ESPN + Sleeper, runs decision rules,
   either auto-fixes + sends FYI, sends a suggestion with buttons, or sends
   nothing. Only this piece needs a clock; it is not "always running."
2. **Telegram webhook handler** — small always-on web service (Railway's cheapest
   tier). Receives button taps (executes the action directly) and free-text
   messages (routes to LLM with live context, replies).

Both share a **core library**: ESPN/Sleeper clients, decision-rule logic, and the
"execute this swap" action — used by both poller and webhook so the auto-fix rules
and the manual-approve path can never drift apart.

**Language/stack (proposed):** Python. `espn-api` for ESPN, direct REST for
Sleeper, `python-telegram-bot` for the bot side, an LLM API for open-chat.

## Open questions / not yet decided
- Exact list of ~60-85 fixed check timestamps for a season (to be generated, not
  hand-written) — need the season start date and week count to compute it.
- Precise auto-fix eligibility-checking logic (slot compatibility rules per
  platform).
- How ESPN cookie refresh gets triggered/reminded (manual for now).
- Repo/service structure details (single Python package with two entrypoints vs.
  two separate services) — leaning toward one repo, one shared package, two thin
  entrypoint scripts (`poller.py`, `webhook.py`).
