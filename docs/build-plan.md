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

## Plan

1. **LLM connectivity spike**
   - Narrow scope: can our own code call an LLM API programmatically and get
     a response back? Not "does Claude work" (it does, we're using it right
     now) — a deployed script needs its own API key/billing account, which
     is a separate thing from an interactive Claude.ai/Claude Code
     subscription.
   - Throwaway script only — no Telegram, no roster data, just one prompt in
     and one response out.
   - Resolves: which account/API key, real per-call cost, rate limits,
     response shape/latency.
   - De-risk early so step 5's actual Telegram-to-LLM plumbing isn't built
     on top of a wrong assumption about how this works.
2. **Data clients**
   - ESPN + Sleeper clients pulling real roster/matchup/injury data for both
     leagues.
3. **Decision rules**
   - Implement the auto-fix / suggest-only rules already specified in
     scope.md's Autonomy section, against real data from (2).
   - Auto-fix sends an FYI; suggest-only sends tap buttons over the same
     Telegram bot from the poller.
4. **Write-path**
   - Implement the "execute this swap" library function itself (the shared
     core-library action from scope.md's architecture) against ESPN/Sleeper's
     APIs.
   - Test it standalone/scripted — no Telegram involved yet.
     - Dry-run first.
     - Then a low-stakes roster.
     - Only then trust it on a league that actually matters.
5. **Interactive Telegram**
   - Stand up the webhook handler as a second, always-on Railway service —
     deferred from the deploy-skeleton work since there was nothing for it
     to receive until buttons/free-text exist to handle.
   - Button taps: wire up real handling for Approve/Dismiss/Show alternatives.
     - A tap just calls the already-tested execute-swap function from (4).
     - This step is only Telegram-side plumbing (receiving the tap, calling
       into it, replying) — not new write logic.
     - Test: deterministic execution end-to-end.
   - Free-text: wire up LLM routing with live roster/matchup context,
     building on the step 1 spike.
     - Test conversationally — ask it real lineup questions.
     - Confirm the context it's reasoning over is actually current/correct.
