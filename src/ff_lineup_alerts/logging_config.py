"""
Shared logging setup for every entrypoint (poller.py today; the eventual
webhook service later) -- one place to define the convention so nobody has
to re-derive it: UTC timestamps (Railway's own log stream is UTC, and a
local-time stamp would silently drift from that), plus module:line so a
log line is traceable back to its source without grepping.
"""
import logging
import os
import time


def configure_logging(level: int | str | None = None) -> None:
    """
    Defaults to the LOG_LEVEL env var (e.g. "DEBUG", "INFO"), falling back
    to INFO if unset -- lets you bump verbosity (DEBUG surfaces the
    Sleeper-cache-hit and ESPN-transaction-payload detail from
    espn_client.py/sleeper_client.py) without a code change, on Railway or
    locally (LOG_LEVEL=DEBUG uv run python -m ff_lineup_alerts.poller ...).
    An explicit `level` argument still overrides the env var.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")

    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03dZ %(levelname)s [%(name)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime  # UTC, not local time

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]
