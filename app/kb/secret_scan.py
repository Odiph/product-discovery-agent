"""Keeps credentials out of the knowledge base.

A research or code document's text crosses MCP (`search_knowledge`) and goes
to a model (`kb digest`), so a `secrets.txt` in a notes folder or a runbook
with a key pasted in would leave the machine the moment it was indexed. Two
checks, both before anything is stored: a file NAMED like a credential is
never read, and a document whose text has a credential's SHAPE is refused.

A refusal names the kind of secret and where it is ("an AWS access key at
line 12"), never the matched text: the reason is printed, and a skip line that
quoted the key would leak it there instead.

This is a shape match, not a guarantee: a password with no label, a key
format not listed here, or a key split across lines still gets through.
"""

from __future__ import annotations

import re
from pathlib import PurePath
from typing import Optional

from app.kb.document import Document

# Whole words of a file name (split on anything not a letter or digit), so
# `tokenization-study.md` and `keynote.md` are read and `github_token.txt` is not.
_NAME_WORDS = frozenset({
    "secret", "secrets", "credential", "credentials", "creds", "password", "passwords",
    "passwd", "token", "tokens", "apikey", "apikeys",
})
_NAME_PAIRS = frozenset({("api", "key"), ("api", "keys"), ("private", "key"), ("access", "key")})
# Anywhere in the suffix chain: `tls.key.md` is a key someone renamed to open it.
_KEY_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".ppk", ".kdbx", ".env"})
_KEY_NAME_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".env", ".netrc", ".pgpass", ".npmrc", ".pypirc")

_SHAPES: "tuple[tuple[str, re.Pattern[str]], ...]" = (
    ("a private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # Short on purpose: a truncated `sk-ant-` key pasted into notes is still one.
    ("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{3,}")),
    ("an API key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}")),
    ("an API key", re.compile(r"\b[rsp]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("a GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("a Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
)
# `api_key = ...`, `OPENAI_API_KEY=...`, `password: "..."`. The value must look
# like a key -- 12+ characters with a letter AND a digit -- so prose such as
# "Password: we reset it monthly" or "token: authentication" is not refused.
_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|access[_-]?key|auth)[A-Za-z0-9_-]*"
    r"[\"']?\s*[:=]\s*[\"']?(?P<value>[^\s\"'`,;]{12,})"
)


def name_refusal(path: PurePath) -> Optional[str]:
    """Why a file is not read at all, or None. Checked before it is opened."""
    name = path.name.lower()
    if name.startswith(_KEY_NAME_PREFIXES) or any(s in _KEY_SUFFIXES for s in PurePath(name).suffixes):
        return "not read: its name says it holds a key or a secret"
    words = [w for w in re.split(r"[^a-z0-9]+", name) if w]
    if _NAME_WORDS.intersection(words) or _NAME_PAIRS.intersection(zip(words, words[1:])):
        return "not read: its name says it holds a secret or a credential (rename it if it does not)"
    return None


def document_refusal(document: Document) -> Optional[str]:
    """Why a document is not stored, or None: the first credential-shaped
    text in its title or sections, by kind and location only."""
    found = _kind(document.title)
    if found:
        return _refusal(found, "its title")
    for section in document.sections:
        found = _kind(section.text)
        if found:
            return _refusal(found, section.location)
    return None


def _kind(text: str) -> Optional[str]:
    for kind, pattern in _SHAPES:
        if pattern.search(text):
            return kind
    for match in _ASSIGNMENT.finditer(text):
        value = match.group("value")
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value):
            return "a credential assignment"
    return None


def _refusal(kind: str, where: str) -> str:
    return (f"not stored: it looks like it holds a secret ({kind} at {where}); "
            f"remove it from the file and add it again")
