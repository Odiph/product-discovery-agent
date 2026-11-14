"""Waiting for a real `app start` child to be running, instead of a fixed sleep.

The tests that drive a real interview used to sleep 8 s and then send
CTRL_BREAK. On an idle machine the child prints its join URL at about 5 s, but
importing `app.main` alone takes 3-4 s (numpy, PyAV, faster-whisper and
ctranslate2 come in through `app/capture/levels.py`), and under the full
suite's load that ran past 8 s. A break that lands before `run_start`
installs its SIGBREAK handler kills the child with exit code 1 (ctranslate2's
bundled Intel runtime prints `forrtl: error (200)`), and the test reported a
shutdown bug that was never there. Measured 2026-11-14: two such failures in
three full runs, none in isolation.

So the test waits for the line the child prints once the server is up, then
gives it the same few seconds of settling the fixed sleep used to leave.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time

RUNNING_MARKER = "Join URL:"
STARTUP_TIMEOUT_S = 90.0
# What the old fixed 8 s left after the join URL on an idle machine.
SETTLE_S = 3.0


class ChildOutput:
    """Reads a child's stdout on a thread, so the test can wait for a line
    with a deadline and still collect everything the child printed."""

    def __init__(self, proc: "subprocess.Popen[str]") -> None:
        self._proc = proc
        self._lines: "queue.Queue[str | None]" = queue.Queue()
        self._seen: "list[str]" = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        for line in self._proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def wait_until_running(self) -> None:
        """Returns once the child has printed `RUNNING_MARKER` and settled.
        Raises AssertionError, with what it printed, if it exits or stalls."""
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError(f"the interview never started:\n{self.text()[-2000:]}")
            try:
                line = self._lines.get(timeout=remaining)
            except queue.Empty:
                continue
            if line is None:
                raise AssertionError(f"the interview exited before it started:\n{self.text()[-2000:]}")
            self._seen.append(line)
            if RUNNING_MARKER in line:
                time.sleep(SETTLE_S)
                return

    def finish(self, timeout: float) -> str:
        """Waits for the child to exit and returns everything it printed.
        Closes its stdin first, as `communicate()` did."""
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc.wait(timeout=timeout)
        self._reader.join(timeout=timeout)
        while True:
            try:
                line = self._lines.get_nowait()
            except queue.Empty:
                break
            if line is not None:
                self._seen.append(line)
        return self.text()

    def text(self) -> str:
        return "".join(self._seen)
