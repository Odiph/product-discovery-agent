"""B5: your own process -- `context/process.md`, a rule layer over the Mom Test.

The operator writes their own rules (what a good question is, what they always
forget, what to never do), one `## heading` per rule so a critique rationale
can cite one by name. `prompts` adds them to the coach's and the critique's
prompt after the Mom Test rubric, as an ADDITION: they can never relax it.

The text is the operator's own, not customer speech. It is sent to the
reasoning vendor with every coach and critique prompt, inside the cached
static prefix.

`<!-- comments -->` are notes to yourself and never reach a prompt. The
starter template `write_template` lays down is nothing but comments, so an
untouched template changes no prompt by a single byte.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.coach.context import ContextValidationError

PROCESS_FILENAME = "process.md"

# A rule layer, not a second rubric: the Mom Test rubric itself is ~5k
# characters. A cap keeps a pasted book out of every cached prefix; refusing,
# rather than truncating, keeps the cut from silently landing mid-rule.
MAX_PROCESS_CHARS = 6000

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_OPEN_COMMENT = "<!--"

_TEMPLATE = """\
<!--
Your own process: the rules you hold yourself to in an interview.

The coach and the critique ALREADY apply the Mom Test. These are built in,
and nothing in this file can switch them off:
  - Talk about their life, not your idea (no pitching).
  - Ask about specifics in the past, not hypotheticals or the future.
  - Don't lead; don't fish for compliments or opinions.
  - Stay on what this interview is for (your survey and hypotheses).

Add your OWN rules below this comment, one heading per rule, so a critique
can name the rule it applied. For example:

## Price waits
Never ask about price before you have walked through their workflow.

## Who else decides
Before the end, always ask who else is involved in the decision.

Everything inside these comment markers is ignored. An empty file, or this
file untouched, changes nothing.
-->
"""


def load_process(context_dir: Path) -> str:
    """The operator's rules, comments removed and trimmed; `""` when there
    are none (no file, a blank one, or only comments). Raises
    `ContextValidationError` for a file that cannot be read or is too long --
    before any device opens, like the brief and survey."""
    path = Path(context_dir) / PROCESS_FILENAME
    if not path.is_file():
        return ""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ContextValidationError(f"cannot read {path}: {exc}") from exc
    text = _COMMENT.sub("", raw)
    if _OPEN_COMMENT in text:
        # A comment opened and never closed: what follows was meant as a note
        # to yourself, so it must not be sent as a rule.
        raise ContextValidationError(f"{path} has a '<!--' comment that is never closed with '-->'.")
    text = text.strip()
    if len(text) > MAX_PROCESS_CHARS:
        raise ContextValidationError(
            f"{path} has {len(text)} characters of rules; the limit is {MAX_PROCESS_CHARS}. "
            "Keep the rules short -- they go into every coach and critique prompt."
        )
    return text


def write_template(context_dir: Path) -> Path:
    """Lays down the commented starter. Raises `FileExistsError` rather than
    overwriting rules someone already wrote."""
    path = Path(context_dir) / PROCESS_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(_TEMPLATE)
    return path
