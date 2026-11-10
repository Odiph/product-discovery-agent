"""Wall-clock bounds for "this call must return at once" tests.

The tests that use this guard against a call BLOCKING on a 2-3 s stub. On this
machine they finish in a few milliseconds, so 50 ms is a tight, honest bound.
A shared GitHub Actions runner stalls for 60-110 ms now and then (observed
2026-11-10, green on re-run), which turned the public badge red over noise.
On CI the bound widens to 0.5 s: still four times under the shortest stub, so
a real block fails exactly as before.
"""

from __future__ import annotations

import os

LOCAL_NONBLOCKING_BOUND_S = 0.05
CI_NONBLOCKING_BOUND_S = 0.5


def nonblocking_bound_s() -> float:
    # GitHub Actions always sets CI=true; any other CI that does is treated alike.
    return CI_NONBLOCKING_BOUND_S if os.environ.get("CI", "").lower() == "true" else LOCAL_NONBLOCKING_BOUND_S
