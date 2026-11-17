"""D-05: the per-run join surface -- an unguessable token and the live-view
URL it opens, on this laptop. This is the ONLY place a join URL is assembled
(03-CONTEXT.md D-05, 03-RESEARCH.md §4).

The server binds the loopback address only (`app/web/server.py::LOOPBACK_HOST`),
so the URL always names 127.0.0.1: the live view is for a browser on this
machine (a second monitor, a side window) and nothing on the network can
reach it.

The per-run token is NOT the OPS-03 "one secret" -- it is generated fresh in
memory every run (03-RESEARCH.md §4) and is never written anywhere on its
own. It is printed (never logged) so a human, and the overlay reading this
process's stdout, can open the page."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

# 128 bits of entropy, ~22 URL-safe characters -- large enough that guessing
# it within an interview's lifetime is infeasible. Never `random`: its own
# documentation rules it out for anything security-relevant (03-RESEARCH.md §4).
TOKEN_NBYTES = 16

LIVE_VIEW_HOST = "127.0.0.1"


@dataclass(frozen=True)
class JoinInfo:
    """Everything a caller needs to print and open the live view."""

    token: str
    port: int
    join_url: str


def generate_join_token() -> str:
    """A fresh, cryptographically-random token. Distinct on every call --
    the property that keeps a token seen once dead the moment this run ends
    (T-03-02)."""
    return secrets.token_urlsafe(TOKEN_NBYTES)


def create_join(*, port: int) -> JoinInfo:
    """Assembles the join surface for one run: a fresh token and the
    live-view URL on this laptop, printed once. Never raises."""
    token = generate_join_token()
    join_url = f"http://{LIVE_VIEW_HOST}:{port}/s/{token}"
    print(f"Join URL: {join_url}")
    return JoinInfo(token=token, port=port, join_url=join_url)
