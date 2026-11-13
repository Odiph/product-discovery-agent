"""The input-token estimate shown before any paid call (`--yes` previews).

Offline and rough, by design: a preview calls nothing. Fitted to the one
billed call on record (MEASUREMENTS.md, 2026-11-12): the follow-up judge's
request, 24,285 characters of JSON (3,494 Hebrew), billed 11,590 input
tokens; this says 11,544. The flat rate used before (4.0 characters per
token) said 6,071: these requests are JSON-dense, and a Hebrew letter costs about a
whole token.
"""

from __future__ import annotations

import json

ASCII_CHARS_PER_TOKEN = 2.7
NON_ASCII_CHARS_PER_TOKEN = 1.0
"""Hebrew, and any other non-ASCII character: about a token each."""
TOOL_OVERHEAD_TOKENS = 350
"""The vendor's own tool-use prompt, added once when the request has tools."""
BASIS = "a rough estimate, fitted to one billed call"


def dumped(request: dict) -> str:
    return json.dumps(request, ensure_ascii=False)


def estimate(request: dict) -> int:
    text = dumped(request)
    non_ascii = sum(1 for char in text if ord(char) > 127)
    overhead = TOOL_OVERHEAD_TOKENS if request.get("tools") else 0
    return round((len(text) - non_ascii) / ASCII_CHARS_PER_TOKEN
                 + non_ascii / NON_ASCII_CHARS_PER_TOKEN + overhead)
