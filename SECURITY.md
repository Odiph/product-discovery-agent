# Security policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue: use
**GitHub's private vulnerability reporting** on this repository (the
"Report a vulnerability" button under the Security tab).

Include what you found, how to reproduce it, and what an attacker could do
with it. This is a solo-maintained project, so expect an acknowledgement
within about a week. Fixes land on `main`; there are no maintained release
branches.

## What this tool handles

Recordings and transcripts of conversations with other people. The most
serious class of bug here is one that exposes that material: to the network,
to another program, to a third party, or to git.

## Security model, and its limits

- **Secrets** (`SONIOX_API_KEY`, `ANTHROPIC_API_KEY`, `COACH_API_KEY`) are
  read from the environment or a git-ignored `.env`. Tests fail if the
  committed MCP configs ever hold a key-shaped value.
- **The live view** is served on `127.0.0.1` only during a call. Every route
  requires a per-run random token, compared in constant time; a wrong token
  gets a generic 404. Every response carries a strict
  Content-Security-Policy, `nosniff` and `no-referrer`, and the WebSocket
  refuses a browser Origin that is not the page's own host.
- **The console, authoring page and hub** bind to `127.0.0.1` only, and check
  the `Host` header and the request `Content-Type`, so another website in your
  own browser cannot drive them.
- **The MCP server** is read-only over stdio. It returns abstracted claims and
  hypothesis standings, never quotes, transcripts, audio or interviewee
  names; a test pins that boundary. `search_knowledge` returns text only for
  your code and for research you typed yourself, never for anything typed by
  guess.
- **The knowledge base** (`kb add`) skips credential-named files and refuses
  any document holding a key-shaped value, and never follows a symbolic link
  or Windows junction out of the folder it was given.
- **The Claude Code plugin** gives another repository that same read-only
  view. Its `/link-discovery` command also writes local deny rules so sessions
  in that repository cannot read this checkout's `projects/`, `sessions/` and
  `context/` directly. Without those rules they could.
- **Local data** under `sessions/` and `projects/` is stored unencrypted. Disk
  encryption (BitLocker) is the protection for a lost or shared machine.

## Supported versions

Only the latest commit on `main`.
