"""Recall and precision of a project's `context/coverage.json` against the
mock interviews' answer key (demo/claudictive-beta/GROUND-TRUTH.json,
`guide_questions_asked`). No model call: run `python -m app coverage
--project claudictive-beta --yes` first, then

    python -m benchmark.coverage_recall projects/claudictive-beta

The number decides whether `prep` may read the model's silence as "never
asked" (prep.item_proposals stays one-way until it does).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parents[1] / "demo" / "claudictive-beta"


def measure(node_dir: Path) -> "dict[str, int]":
    truth = {Path(e["file"]).name: {q["id"] for q in e["guide_questions_asked"]}
             for e in json.loads((DEMO / "GROUND-TRUTH.json").read_text(encoding="utf-8"))["interviews"]}
    cache = json.loads((node_dir / "context" / "coverage.json").read_text(encoding="utf-8"))
    hits = found = expected = 0
    for row in cache["sessions"]:
        meta = json.loads((node_dir / "sessions" / row["session_id"] / "session.json").read_text(encoding="utf-8"))
        asked = truth.get(meta.get("imported_from", ""))
        if asked is None:
            continue
        got = set(row["asked"])
        hits += len(got & asked)
        found += len(got)
        expected += len(asked)
    return {"really_asked": expected, "found": found, "correct": hits}


def main(argv: "list[str]") -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    m = measure(Path(argv[0]))
    recall = m["correct"] / m["really_asked"] if m["really_asked"] else 0.0
    precision = m["correct"] / m["found"] if m["found"] else 0.0
    print(f"recall {m['correct']}/{m['really_asked']} = {recall:.0%}; precision {m['correct']}/{m['found']} = "
          f"{precision:.0%} (the word match: 52/109 recall, 100% precision)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
