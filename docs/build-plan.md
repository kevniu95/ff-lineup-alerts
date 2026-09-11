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

## Plan

1. **Deploy skeleton**
   - Stand up the two Railway services (cron poller + webhook handler);
     decide plan/cost.
   - Confirm the poller fires on schedule — test both a conditional-fire and
     a no-fire case.
   - Confirm it can send a real Telegram message — the minimum needed to
     observe the result of a cron fire at all.
   - In parallel: throwaway spike of Telegram-message-in → LLM-call-out,
     nothing wired to real data yet.
     - Biggest open question: which LLM account/API, cost per call.
     - De-risk early so it doesn't force a rework of step 5 later.
2. **Data clients**
   - ESPN + Sleeper clients pulling real roster/matchup/injury data for both
     leagues.
3. **Decision rules**
   - Implement the auto-fix / suggest-only rules already specified in
     scope.md's Autonomy section, against real data from (2).
   - Auto-fix sends an FYI; suggest-only sends tap buttons over the same
     Telegram bot from step 1.
4. **Write-path**
   - Implement the "execute this swap" library function itself (the shared
     core-library action from scope.md's architecture) against ESPN/Sleeper's
     APIs.
   - Test it standalone/scripted — no Telegram involved yet.
     - Dry-run first.
     - Then a low-stakes roster.
     - Only then trust it on a league that actually matters.
5. **Interactive Telegram**
   - Button taps: wire up real handling for Approve/Dismiss/Show alternatives.
     - A tap just calls the already-tested execute-swap function from (4).
     - This step is only Telegram-side plumbing (receiving the tap, calling
       into it, replying) — not new write logic.
     - Test: deterministic execution end-to-end.
   - Free-text: wire up LLM routing with live roster/matchup context,
     building on the step 1 spike.
     - Test conversationally — ask it real lineup questions.
     - Confirm the context it's reasoning over is actually current/correct.
