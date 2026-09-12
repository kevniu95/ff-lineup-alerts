# Project conventions

## Branch and commit naming

Every unit of work gets its own branch, named `ff-lineup-NNNN` (4-digit,
zero-padded, sequential — not tied to a GitHub issue number, just an
incrementing counter). Branch off `main`.

Every commit on that branch is prefixed with the same identifier:

```
ff-lineup-0001: short description of this commit
```

**Why:** `main` has branch protections on GitHub, so work always lands via a
branch; the numbered prefix makes it easy to see which commits belong to the
same unit of work once merged, without relying on GitHub PR links.

**How to apply:** Before starting a new branch, check the most recent
`ff-lineup-NNNN` branch/commit (local or on GitHub) and increment from there.

## Logging, not print

App code under `src/ff_lineup_alerts/` uses Python's `logging` module, not
`print` — follow `poller.py`'s pattern (`logging.basicConfig(...)` once,
module-level `logger = logging.getLogger("<module>")`, `logger.info` /
`.warning` / `.error`).

**Why:** unleveled, untimestamped `print` output gets hard to read once
Railway's log stream carries more than one module.

**Exception:** one-off scripts (`scripts/spike_llm_*.py`) that aren't part
of the deployed app can keep using `print`.
