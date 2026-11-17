# Product Discovery Agent: the full guide

Live bilingual (Hebrew/English) interview transcription: captures the
interviewee's audio via WASAPI loopback and the interviewer's own microphone
as two independent streams, transcribes both live, and writes a durable,
speaker-labelled transcript to disk while the call is running.

On top of the transcript sits a **live coach**: during the call it suggests
your next question, held to the Mom Test (ask about past behaviour, never
pitch, never fish for compliments), and grounded in the survey and hypotheses
you wrote beforehand. Afterwards it extracts claims into a local evidence
corpus and shows where each hypothesis stands across interviews. Windows only.

**No code yet?** Start with [version 0](version-0.md): the same process as
one prompt and a checklist.

## Quick start

1. **Read "Privacy, consent and data flows" below first.** You are recording
   other people.
2. Clone to a short path and install (Python 3.12+):
   ```
   git clone https://github.com/Odiph/product-discovery-agent C:\src\product-discovery-agent
   cd C:\src\product-discovery-agent
   py -3 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   copy .env.example .env
   ```
   Put your `SONIOX_API_KEY` (speech-to-text) and `ANTHROPIC_API_KEY` (the
   coach) in `.env`.
   `.venv\Scripts\python.exe -m app setup` checks the machine.
3. Write what the interview is for: `.venv\Scripts\python.exe -m app author`
   opens a local page for the brief, survey and hypotheses. The coach judges
   every question against them.
4. Check both audio sides carry sound: `.venv\Scripts\python.exe -m app precheck`.
5. Record: double-click `start-overlay.bat`, or run
   `.venv\Scripts\python.exe -m app start`. Stop with Ctrl+C.
6. Afterwards: `render` for a readable transcript, `extract` to pull claims
   into the corpus, and `hub` to review the opportunity tree and where each
   hypothesis stands. Every
   subcommand has `--help`; the sections below cover each in depth.

The rest of this guide is the full operating manual, written from real use,
so it goes into far more detail than a first run needs.

## Privacy, consent and data flows

This tool records conversations with other people. Read this before the
first call.

**Consent is yours to get.** This is not legal advice, and the rules differ
by place:

- **Some places require every party's consent**, for example California
  (Penal Code 632). Software cannot tell which rule applies to a given call,
  so ask everyone, every time.
- **In the EU (GDPR)** a voice recording is personal data: you need a lawful
  basis, and before recording you must tell the interviewee who you are, why
  you record, who receives the data (the vendors below) and how long you keep
  it.
- **In Israel** a participant may record a conversation they take part in, and
  the Protection of Privacy Law (including Amendment 13, in force since August
  2025) governs what you then do with the recording and transcript.

Say at the start of every call that you are recording, transcribing and using
an AI assistant, and get agreement before you press Start. Nothing in this
tool asks for or records consent on your behalf.

**What leaves your machine, and to whom:**

| Data | Sent to | When |
|---|---|---|
| Live audio of both sides | Soniox (speech-to-text) | Throughout every recorded call |
| Transcript text, your brief, survey, hypotheses, your own rules (`process.md`) and prior claims | Anthropic, or the OpenAI-compatible endpoint you configure (`COACH_BASE_URL`) | Every coaching cycle during a call, and when you run `extract` or `critique-questions`. `missed --group model --yes` (and `themes --group model --yes`) sends the extracted claims once, never quotes; `missed --group model --yes` then sends, once, YOUR OWN turns (the question right before each recurring topic, and up to two of your questions before it) with the topic labels, and then, once more, your next turns after each time a recurring topic came up with the same labels; never the interviewee's words, so under `--group model` it is no longer claims only. `coverage --yes` sends your own turns of imported interviews and the survey, once |
| Every extracted claim in the project (claim text, interview id, which hypotheses it bears on), your hypothesis statements with their kind and parent, your outcome, and the previous synthesized tree's node labels and structure; never a quote, never a transcript, never a falsifier or criterion | The same coach endpoint, to the judge model | Once, when you run `synthesize --yes`; again only after the claims, the hypotheses, the outcome, the model or the prompt change |
| What `prep` already shows you: each gap (the hypothesis, its kind, why it is a gap), the survey's questions, your brief items (from `brief.json` only, never the claims the coach's brief adds), the hypothesis statements, the mirror's habit labels and `missed`'s topic labels. Never anything an interviewee said | The same coach endpoint, on `JUDGE_MODEL` | When you run `prep --draft --yes`, once per change to any of them; never without `--yes` |
| Code you added with `kb add`, and research you typed yourself with `kb add --type research` (never interviews, conversations, emails, or anything typed as research by guess) | The same coach endpoint | When you run `kb digest`, once per new or changed document. Its notes then ride in the coach's prompt every cycle |
| A recording you import (`import <file>.wav --yes`) | Soniox: the whole file, uploaded for the same file pass `diarize-after` runs (their copy is deleted afterwards) | Once per imported recording, and again only if you re-run `diarize-after` on it. Never without `--yes` |
| Retained audio (`--retain-audio`, off by default) | Nothing: the WAV files stay on this machine | Never |

Each vendor's own policy governs retention and training use, and they change,
so read them before recording anyone: [Soniox security and
privacy](https://soniox.com/docs/security-and-privacy), [Anthropic API data
retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention).
If you process other people's personal data, a data processing agreement with
each vendor is your responsibility. To avoid a vendor, set `COACH_BASE_URL` to
a model you run yourself; without `ANTHROPIC_API_KEY` and `COACH_BASE_URL` the
coach is simply off and only Soniox receives anything. Nothing is sent
anywhere else: no telemetry, no analytics. The one other outbound request is
`fetch-voiceprint-model`, a one-time download from GitHub that sends nothing
of yours.

**Voiceprints (imported recordings only).** To tell the two people on one
recording apart, `diarize-after` computes a voiceprint (a speaker embedding)
for each voice from the first two minutes of the recording. Voiceprints are
kept in memory only, never written to disk, never sent anywhere, and are gone
when the command ends. Some laws treat a
voiceprint as biometric data: Illinois's BIPA requires written consent before
one is collected, even briefly, and GDPR Article 9 and Israel's Privacy
Protection Law (Amendment 13) may count it as specially protected data. Name
it in your consent line: "...and the software tells our
voices apart by voiceprint, which it does not keep".

**What stays on your machine:** transcripts, session metadata, extracted
claims and hypotheses, and the knowledge base (`kb`, below), under `sessions/` and `projects/`. Both are
git-ignored in full. They hold verbatim speech, so treat the folders as
confidential and delete sessions you no longer need. If someone asks you to erase their data, run
`.venv\Scripts\python.exe -m app forget <session_id> --project <node>` (leave
out `--project` for a root session). It lists what it would delete, as counts
and paths with no transcript text, and deletes only when you add `--yes`. It
removes the session directory (transcript, kept recording, renders, critiques),
that interview's rows in `context/facts.json`, `rejections.json`,
`demotions.json` and `declined_proposals.json`, and any knowledge-base copy
made with `kb add --sessions`. A file it cannot read is left untouched and
named, so repair it and run the command again. A session with the same id in
another project is reported, not deleted. It does not reach copies you made
yourself (exports, backups, moved files, a transcript re-added as a plain
file) or what Soniox or your coach provider keep under their own retention
terms.

**A note on the code comments.** Many comments cite design notes such as
`04-01-PLAN.md`, `03-RESEARCH.md` or `STATE.md`, and phase or gate numbers.
Those are the maintainer's private planning records and are not published;
the comments around each citation carry the reasoning that matters.

**Who can reach the running app:** nothing outside this laptop. During a call
the live view is served on `127.0.0.1` only (port 8765), and every route on it
requires a random token generated fresh for that run. The console, the
authoring page and the hub listen on `127.0.0.1` only too. The MCP server is
read-only and never returns quotes, transcripts, audio or interviewee names. See `SECURITY.md`.

## Setup (first run on a new machine)

Windows only, and not by accident: `PyAudioWPatch` ships `win_amd64` wheels
only, and WASAPI loopback captures the **host** machine's default render
endpoint. There is deliberately no devcontainer — a container cannot record
this. Python 3.12+ with the `py` launcher (a standard python.org install).

```
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

That is where the `.venv\Scripts\python.exe` named throughout this file comes
from. Every command below assumes it exists; a bare `python` is the system
interpreter, has none of these pinned packages, and will silently do something
else.

**Keep the checkout path short** (e.g. `C:\src\product-discovery-agent`), or enable
Windows long paths. The `anthropic` package ships module names long enough that
a venv nested ~120 characters deep crosses Windows' 260-character limit, and
every import of the coach then fails with a `ModuleNotFoundError` that names a
file which is plainly there.

Then copy `.env.example` to `.env` in the repository root and fill it in —
never committed, never a CLI argument:

```
SONIOX_API_KEY=...
ANTHROPIC_API_KEY=...
```

`SONIOX_API_KEY` is the speech-to-text vendor: without it nothing transcribes.
`ANTHROPIC_API_KEY` is the coach's reasoning vendor: without it the transcript
still records perfectly and the live suggestions simply never appear.

**Stop a running interview with Ctrl+C in the terminal — never an editor's
terminate / trash-can button.** That button is `TerminateProcess`: the process
dies where it stands, `session.json` never gets its `closed_at`, and the
transcript keeps whatever partial tail was mid-write. Or
double-click `start-overlay.bat` or `open-console.bat`; both are
workspace-relative and run from wherever the repository is checked out.

## Before a call (9:58 for a 10:00 call)

```
.venv\Scripts\python.exe -m app precheck
```

Play the call app's test audio (or wait for the interviewee to speak) and say
something into the microphone while it runs. It prints one PASS/FAIL row per
check — both devices resolve, both streams carry REAL audio above a level
threshold (not merely "the device opened"), and the STT engine answers within
its network timeout. **Any FAIL exits non-zero and prints a specific remedy.**
Fix every FAIL before starting — a precheck that passes on a muted device is
worse than no precheck at all.

Skip the engine-reachability row (e.g. to check audio only, with no network
call) with `--skip-stt`. Shorten or lengthen the listening window with
`--seconds N` (default 3).

## Starting a call

```
.venv\Scripts\python.exe -m app start
```

Captures and transcribes both sides at once until you press Ctrl+C, or for a
fixed duration with `--seconds N`. To run only one side (debugging one half of
a broken setup), add `--only interviewee` or `--only interviewer`.

`start` also serves the live transcript from inside this same process — one
command, one process, no deployed service. It prints the live view's URL
(`http://127.0.0.1:8765/s/<token>`) and opens it in a browser on this laptop;
the server listens on `127.0.0.1` only. The web port is pinned (`8765` by
default — change it with `APP_PORT` if it's ever taken) so the printed URL
always matches what's actually listening.

> **One process per interview, with one exception.** The overlay is a second
> process: it spawns `python -m app start` as a child
> (`app/overlay/session.py`). The rule that holds everywhere is narrower —
> **a web page never spawns a subprocess.** The
> console proves it: pressing Start stops the page's own server and the *same*
> process runs the interview. The overlay is the one deliberate exception, and
> it earns it by being a real supervisor rather than a launcher — it holds the
> child's stdin control pipe, drains its stdout so it cannot deadlock, delivers
> CTRL_BREAK on stop, and checks the child's exit code instead of assuming a
> clean close. Nothing outlives what launched it.

Need to run `start` with no browser and no server at all (e.g. the
single-side trap tests, or debugging capture in isolation)? Add `--no-serve`.
Serving is not a separate mode you opt into — it's what `start` does by
default; `--no-serve` is the one flag that opts back out.

**Pre-flight rules — not fixable in code, read them every time:**

- Fix your call output device (Zoom/Meet/Teams) *before* pressing start.
  **Do not change it mid-call** — the loopback stream stays bound to whatever
  was default when it opened; plugging in headphones mid-call is detected and
  triggers one automatic re-open, but is still slower and riskier than not
  changing it at all.
- Disable sleep / set the power plan to "never sleep" for the call's duration.
- Loopback captures **everything the machine plays**, not just the call app —
  close other audio sources (music, notifications) before starting.
- If a second monitor is in use, set your screen-share selection to that
  single window or display *now* — never "entire desktop" or "all displays".

## Pre-call checklist (sixty seconds before a customer interview)

Run this down in order, every time, before a real call — not during one:

0. Author the brief, survey and any hypotheses (`python -m app author`) well
   before the sixty-second countdown starts, never during it — see
   "Grounding the coach" below. Confirm `context/brief.json`,
   `context/survey.json` and `context/hypotheses.json` are the ones for
   *this* interview, not left over from a previous customer. **Interview #1
   always has an empty `context/facts.json`** (nothing has been extracted
   yet) — with no facts extracted, the coach simply has no past interviews to
   draw on, which is not a fault.
1. Run `precheck` and get **every row green**.
2. If using a second monitor, set your screen-share selection to that single
   window or display now.
3. Disable notifications (browser and OS) for the surface's origin — a
   notification banner can leak the surface even when nothing else is shared.
4. Confirm the coach is live *before* the call, not during it: `start`'s own
   startup line reads `Coach enabled: brief has N item(s), survey has M
   item(s).` when `ANTHROPIC_API_KEY` is set and both files loaded. If it
   instead prints `Coach disabled: ...`, that is a decision to make now —
   capture and transcription still work either way, but a mid-call surprise
   about missing suggestions is what this step exists to prevent.
5. Start the session (`start`), then start the call.

## Screen-sharing during the call

- Share **only the video-call application window**. If full-screen sharing is
  unavoidable, pick the single monitor that does **not** have the surface
  open — never "entire desktop" or "all displays".
- If you're using the second monitor instead, picking the correct single
  display share target is a checklist item, not something the app solves for
  you.
- Disable browser and OS notifications for the surface's origin — a
  notification banner is a leak vector independent of what you actually
  share. The browser window title is already generic; don't rename the tab.

## Secrets

Two secrets to manage, both the same discipline: the environment or a local
`.env` file, never committed, never a CLI argument.

- **`SONIOX_API_KEY`** (and `ASSEMBLYAI_API_KEY` if used) — the STT vendor.
- **`ANTHROPIC_API_KEY`** — the coach's reasoning vendor. If it's
  absent, `start` prints `Coach disabled: ...` and runs anyway — capture and
  transcription are completely unaffected; you just get no suggestions. See
  "Grounding the coach" below.

### Pointing the coach at a different model

The coach takes its client by injection and speaks two dialects, so any
OpenAI-compatible endpoint works — a local runtime (Ollama, vLLM, llama.cpp) or
a hosted provider (OpenRouter, Groq, Together, DeepInfra, Fireworks). Three
variables, all read from the environment like every other secret:

```
COACH_BASE_URL=https://openrouter.ai/api/v1
COACH_API_KEY=...
COACH_MODEL=google/gemini-2.5-flash
```

**`COACH_BASE_URL` wins outright.** When it is set, `ANTHROPIC_API_KEY` is not
consulted at all — which is deliberate.

**`COACH_MODEL` is not optional here.** The default is a dated Anthropic model
id and means nothing to another provider, so pointing the coach elsewhere
without naming a model sends that endpoint an id it has never heard of.

**`EXTRACT_MODEL` buys quality with latency nobody is waiting on.** The live
coach answers inside a ~8s cycle while an interview is happening, so its model
is chosen under a latency bound. Extraction runs *after* the interview ends —
so a slow, strong model there costs money and nothing else. It is the one
place in this system where quality is free.

```
EXTRACT_MODEL=anthropic/claude-opus-4-5
```

Unset, it falls back to `COACH_MODEL` and changes nothing. It selects a
*model*, not a *provider*: there is one client construction site, so whatever
you name has to be served by the same `COACH_BASE_URL` endpoint.

**`JUDGE_MODEL`** picks the model for the two judgments made over your own
questions: whether you had already asked about a topic (`missed --group
model`) and which guide questions you asked (`coverage`). Unset, it is
`EXTRACT_MODEL`. Pick a strong one: on a set of synthetic interviews `gemini-2.5-flash`
put the planted topic at 7 interviews in one run and 3 in the next, while
`claude-sonnet-5.5` matched the answer key. Each cache records its model, so
changing it re-judges once and never reuses the old answer.

```
JUDGE_MODEL=anthropic/claude-sonnet-5.5
```

Worth setting, because the extraction model is measurably the weak link: it
labels merely-implied claims `evidence`, at 3/18 on a hand-adjudicated real
interview. `app/coach/extract.py`'s own docstring carries the measurement and
the two failure modes.

**Choosing a model is a measurement, not a preference.** A labelled question set was run
through the real critique path, to see whether each model can hold a forced tool call
against the real rubric at all.

Measured over 3 runs of 17 labelled cases each. `judged` is the gate
that matters: a model that cannot emit the tool call is not a cheap coach, it
is not a coach.

| model | judged | rules caught | band flips | s/call | $/interview |
|---|---|---|---|---|---|
| `google/gemini-2.5-flash` | 17/17 | 5/5 | 0 | 2.85 | 1.87 |
| `anthropic/claude-haiku-4.5` | 15.7/17 | 4.7/5 | 4 | 4.95 | 5.82 |
| `mistralai/mistral-nemo` | 7/17 | 1.3/5 | 13 | 4.29 | 0.10 |

Five further models — `openai/gpt-5-nano`, `openai/gpt-oss-120b`,
`qwen/qwen3.5-flash`, `z-ai/glm-4.7-flash` and both local `qwen2.5` sizes —
failed the tool-fidelity gate outright and are not candidates at any price.

Two caveats that keep those numbers honest. Both `$/interview` figures assume
**no prompt cache**, because the OpenAI-compatible seam drops `cache_control`
(see `app/coach/openai_seam.py`) and prefill is roughly 8× without one; Haiku
**direct** through the Anthropic SDK, where caching does apply, measured
**$1.05**. And this compares Haiku *through OpenRouter*, not Haiku direct — the
parse errors and band flips in that row may belong to the translation rather
than to the model.

The token embedded in the live view's URL is **not** a secret to manage — it's
generated fresh in memory every run, never written anywhere, and dies the
moment that run ends. There's nothing to store or protect about it beyond not
leaving old live-view URLs lying around.

## Projects: running several lines of enquiry at once

A project is a **nested label** — a product, a feature within it, a hypothesis
within that. Nesting is directory nesting, so a project path looks like
`acme/onboarding/activation-delay` and lives under `projects/`:

```
projects/acme/onboarding/
  context/     brief.json, survey.json, hypotheses.json, facts.json
  sessions/    interviews filed at THIS node
```

Pass `--project` to `start`, `render`, `author` or `extract`:

```
python -m app author  --project acme/onboarding
python -m app start   --project acme/onboarding
python -m app extract --project acme/onboarding 20260810T143000
```

`precheck` deliberately does **not** accept it — it touches neither directory,
so a project there would be an argument it silently ignored.

**Omit `--project` and nothing changes**: the root `context/` and `sessions/`
are used, exactly as before projects existed.

**All of `projects/` is git-ignored, blanket.** That rule has to stay blanket:
`projects/*` with a `!projects/*/context/*.example.json` negation looks like it
would let format samples live in the tree, but git never descends into an
excluded directory, so the negation is never consulted. The samples stay in the
root `context/`, which is what lets this rule be total. A test asserts it.

### Drawing on another project's knowledge

By default the coach is grounded in the filing node alone. `--read-from` adds
another node's **facts and hypotheses**, read-only, and is repeatable:

```
python -m app start --project acme/onboarding --read-from acme/billing
```

The rules, all enforced rather than documented:

- **Same hierarchy only.** A node under a different root is refused. Knowledge
  is shared within one product, never across two customers.
- **Reads merge; writes never do.** Extraction always writes to the filing
  node. A source node's files are left byte-identical.
- **The brief and survey always come from `--project` alone.** They are what
  *this* interview is about; merging another node's survey would quietly change
  the questions you ask in the room.
- **Facts are pooled, then selected once**, so the retrieved-fact cap still
  means what it says — three sources do not put three times the facts into the
  brief.
- **Merged fact ids are qualified** with the node they came from
  (`fact:acme/billing:<id>`). Session ids are only unique *within* one root, so
  two projects can mint the same one; unqualified, two customers' facts would
  read as a single provenance chain.

Every rejection is an error, never a silent skip — a dropped source would mean
the coach ran on less grounding than you selected while reporting success, and
you would blame the model for the thinner suggestions.

While a projected session runs, the overlay shows a small strip naming the
project and its extra sources, so you can always see which knowledge is in
play. It is hidden entirely for an unprojected run. Note it renders the node
paths on a screen that may be sitting in a cafe: if you name a node after a
customer, that name is on the screen. The session's `session.json` records the
same two fields for later.

### The console: pick a project, then start

```
python -m app console
```

or double-click **`open-console.bat`**. A loopback-only page opens showing the
project tree; select a node and you see its survey, its hypotheses with their
states, how many facts it has accumulated, and its past interviews. Tick any
in-branch nodes to also draw on, then press **Start**.

**The console and the interview are one process.** Pressing Start stops the
page's server and the same process runs the interview — **a web page never
spawns a subprocess** (see "Starting a call" above for the overlay, the one
process that does). So leave the terminal open and read it once you have
pressed Start; that is where the interview reports from. Ctrl+C before choosing
cancels without starting anything.

The console **only reads**. No route it exposes changes anything on disk, and
it shows a fact COUNT rather than any fact — a fact carries a previous
customer's verbatim speech, and this is a browser page. Authoring stays where
it was, on `python -m app author`.

It carries the same two guards as the authoring page (loopback bind, Host
header, JSON `Content-Type`) because the loopback bind stops the LAN but not
your own browser. Here the consequence of getting that wrong is worse than the
authoring hole those guards were added for: a cross-origin POST would choose
which customer's knowledge grounds your next interview.

One limitation, stated rather than discovered: `DEFAULT_APP_PORT` (8765) and
`DEFAULT_AUTHOR_PORT` (8766) are fixed and never auto-chosen, so two projects
cannot run at once. That is acceptable given the one-PyAudio-instance rule,
which already forbids two concurrent interviews on one machine.

### Keeping test sessions apart

Keep rehearsals and test recordings in their own project, for example
`projects/_eval/`, and declare it `{"corpus": "demo"}` in its `project.json`
so its claims are never mistaken for customer evidence:

```
python -m app render --project _eval <session-id>
```

A bare `python -m app start` with nothing in the root `context/` tells you to
author a brief first; that is the default behaviour, not a fault.

## Grounding the coach: the brief, the survey, and hypotheses

The authoring page (`python -m app author`) now carries **three** things, all
under `context/` and all git-ignored (the brief can name a real customer —
this is the most sensitive plaintext this repository ever produces, and
hypotheses are right behind it: each one names a bet you're making about that
same customer):

- **`context/brief.json`** — what you know or suspect about the interviewee,
  as a list of items. Each one is labelled `"provenance": "evidence"` (you
  were told this, or read it somewhere) or `"provenance": "inference"` (you're
  guessing). There's no default — a missing or misspelled provenance value
  fails to load rather than silently becoming "evidence".
- **`context/survey.json`** — the ordered list of questions you plan to ask.
  The coach tracks which ones the *interviewer* (you) actually asked, from
  your own microphone stream — never from a suggestion shown, whether or not
  you followed it.
- **`context/hypotheses.json`** — what you believe about this
  customer, stated so it can be proven wrong. Every hypothesis needs a
  **falsification condition** — what evidence would make it FALSE — and the
  page refuses to save one without it: a hypothesis nobody could ever
  disprove gives the coach nothing to target when it steers toward the
  question that would settle it. A new hypothesis always starts
  **`"state": "untested"`**; the state is yours to change as evidence comes
  in — nothing in this codebase changes it for you yet. Today, hypotheses are
  read by `python -m app extract` for tagging only (each extracted fact may
  reference the hypothesis it bears on); nothing else reads or writes them.
- **`context/process.md`** (optional) — your own interviewing rules, added on
  top of the Mom Test that the coach and `critique-questions` already apply:
  what a good question is for you, what you always forget, what you never do.
  One `## heading` per rule, so a critique can name the rule it used. Your
  rules add to the Mom Test and can never relax it. `python -m app process init`
  writes a starter that only has comments in it. Comments never reach a
  prompt, so an empty or untouched file changes nothing.

Copy the shipped format samples to get started:

```
copy context\brief.example.json context\brief.json
copy context\survey.example.json context\survey.json
copy context\hypotheses.example.json context\hypotheses.json
```

The brief and survey are read **once**, at `start`, and copied into that
session's own metadata — editing them mid-call never re-grounds a session
already running. `start` **fails loudly**, before anything else happens, if
either file is missing or malformed. `start` **warns** (but proceeds) if
either file predates your previous session — a stale brief from a different
customer is a realistic and expensive mistake, but only you can tell "stale"
from "deliberately reused". Hypotheses are read separately, by
`python -m app extract`, at extraction time — see "Extracting facts" below.

If `ANTHROPIC_API_KEY` is absent, none of this is even read — the coach is
disabled and the session records a transcript only.

## Where the transcript goes

Every run creates a new timestamped directory under `sessions/` (gitignored —
confirmed with `git check-ignore`, never by reading `.gitignore`) containing:

- `transcript.jsonl` — one JSON record per line, append-only, `fsync`'d after
  every write so a crash never loses what was already captured. Segment
  records carry `speaker` (`interviewee` or `interviewer`), `text`,
  timestamps, and a *measured* latency. Health/trap events (idle, recovered,
  lagging, dropped, device-changed, dead, stream-failure, ...) interleave in
  the same file, in the order they happened.
- `session.json` — provenance: both device names, both native sample rates as
  reported by the driver, the resolved engine, start/close times, whether
  audio was retained (`audio_retained`), a per-speaker latency summary, and —
  when there is one — `participant`, who was interviewed.

  `participant` is optional and its ABSENCE is the normal state: pass
  `--participant "Dana (ops lead)"` to `start`, or fill it in afterwards on the
  hub, which also clears it. The key is omitted entirely when nobody is named
  rather than written as `null`. It exists because per-interview counting
  counts *sessions*, which is the same as counting people only while nobody is
  re-interviewed — the label does not change the count, it makes the count
  checkable by a human.
- `transcript.md` — only after `python -m app render` is run (see below).
- `interviewee.wav` / `interviewer.wav` — only if `--retain-audio` was passed
  (see below). Already covered by the existing `*.wav` ignore rule.
- Imported recordings only: `room.wav`, the session's copy of the imported
  audio, kept **without** any flag so `diarize-after` can re-pass it, and
  deleted by `confirm-speakers --confirm`. Until then it is a full recording
  of a real person. Also `evidence.jsonl`, the slower evidence pass's turns.

## Reading the transcript after the call

```
.venv\Scripts\python.exe -m app render <session-id-or-path>
```

Writes `transcript.md` into the session directory: both speakers interleaved
in strict time order, merged into paragraphs per speaker turn, with health
events (idle, device-changed, ...) shown inline at the point they happened,
and a per-speaker latency summary (count, median, p95) at the end. Segment
text is reproduced exactly as the engine emitted it -- mixed Hebrew/English
lines are never reordered or "fixed". Works on a session that crashed or is
still running; it says so in the output rather than failing.

**This same document is also where every coach decision gets audited.** Inline, in the same session-time order as the transcript itself:

- **Every suggestion the coach ever produced** -- shown, ranked down, *and
  dropped* -- with its move type (`advance`/`deepen`/`fill_gap`/
  `test_hypothesis`), its band, its five named per-rule flags, and its
  rationale. Read the dropped ones: a high drop rate concentrated on one
  flag means the critic rubric is over-firing on real calls, and that is
  the single most useful tuning signal the post-call document gives you.
- **Which past-interview facts grounded a suggestion.**
  A `grounded in:` line under a suggestion prints the fact's claim and its
  **verbatim quote from that earlier interview** -- this document is the
  ONLY place in the whole tool a past interview's exact words are ever
  shown; they never reach the live view or the live call itself. If a
  suggestion cites an id that resolves to nothing, that's normal, not
  corruption: fact ids are re-minted every time you re-run `extract`, so an
  id from before your last re-extraction won't match anymore.
- **A proposed hypothesis-state change.** A line reading
  `PROPOSED (not applied): hypothesis ... -> '...'` means the coach thinks
  the evidence points that way -- **nothing has changed yet.** The
  hypothesis set changes only when *you* change it, on the authoring page
  (`python -m app author`) -- there is no other accept surface, and reading
  this line is the whole workflow: decide whether you agree, then go set it
  yourself.
- **The FULL coverage transition history** -- every survey question the
  coach marked as asked, and what interviewer sentence it matched against;
  every segment it considered and found no match for too. **This is where
  you check whether the coach quietly stopped tracking a question:** a
  false-positive match silently removes that survey item from attention for
  the rest of the interview, and reading "matched X against Y" side by side
  is the only place that mistake is ever catchable after the fact.
- A closing **`## Coaching summary`** -- cycles completed, suggestions
  shown, candidates dropped broken down by which rule fired, coverage
  counts, how many suggestions were grounded in a past-interview fact (and
  how many distinct facts were cited), how many hypothesis-state changes
  were proposed (with the same not-applied reminder), and the coaching
  latency figures (session-start grounding, first cycle, and remaining
  cycles, reported separately). Reports all-zero, without failing, for a
  session where the coach never ran -- including every session recorded
  before this phase existed.

### Extracting facts

```
.venv\Scripts\python.exe -m app extract <session-id-or-path>
```

The one command to run after an interview. Reads the session's transcript
and writes cited, provenance-tagged facts into `context/facts.json` -- the
same directory the brief and survey live in, under the identical
git-ignore rule. **`context/facts.json` and `context/hypotheses.json` are
never committed, on purpose:** they carry verbatim customer speech, exactly
like `context/brief.json` already does. Nothing here changes that.

**Safe to re-run.** Running `extract` again on the SAME session *replaces*
that session's facts with the new run's -- it never doubles the corpus. This
matters in practice: a prompt fix, a model swap, or just re-running because
something looked off should never leave two versions of one interview's
facts sitting side by side, reading as if two different customers said the
same thing. Every OTHER session's facts are left completely untouched by a
re-run.

**A non-zero exit means at least one returned claim was rejected** -- the
run still writes every fact that WAS accepted; only the rejected ones are
dropped. Look at the printed report, not just the exit code: each rejection
names the claim and one of two reasons, and the two point at different
problems --

- `unresolved-citation` -- the model cited a segment that doesn't exist in
  this session's transcript (a miscounted or hallucinated `seq`).
- `unlocatable-quote` -- the claim was labelled `evidence`, but its quoted
  text isn't really, verbatim, in the segment it cites. Either the model
  paraphrased instead of quoting, or the claim is really an inference that
  got mislabelled.

**If extraction refuses to run at all** (exits non-zero *before* printing
any per-claim report), the EXISTING corpus at `context/facts.json` failed
to parse -- the run stops before the vendor is ever called, and the message
names the file (and, where possible, the offending item). Nothing was
overwritten or lost; fix or restore that file, then re-run.

**If you see `WARNING: session ... has no closed_at marker`**, the session
you pointed at was never closed -- extraction still runs; this is a
warning, not a refusal. Only you can tell a deliberate mid-interview sanity
check from a forgotten crash, so the fact set is written either way, but
treat it as possibly incomplete if the interview is genuinely still going.

**Roughly what one extraction costs:** every run prints the accepted and
rejected counts plus the call's own token usage, when the response reports
it. This is a per-interview batch cost, not a per-utterance one -- check the
printed numbers against a few real interviews rather than trusting a
one-line estimate; that is exactly what these numbers are for.

**`extract --all`** extracts every interview in the project that has no facts,
rejections or demotions yet, oldest first. Without `--yes` it lists them with
an estimated input-token count and calls nothing; with `--yes` it runs them
one at a time, keeps going past a failure, and prints a per-interview summary.
`--force` extracts the already-extracted ones too.

### Importing past interviews

```
.venv\Scripts\python.exe -m app import <file-or-folder> --project acme --me "Your Name" [--date 2026-03-04] [--participant "Dana"] --yes
```

Turns transcript exports (`.vtt`, `.srt`, or a `Name: text` `.txt`/`.md` from
Otter, Granola or Meet) into sessions, one per file, so `extract`, `standing`,
`themes`, `mirror`, `critique-questions` and `forget` can use them. `--me` is
your speaker name as the file spells it: your turns become the interviewer's,
everyone else's the interviewee's. Without `--yes` it shows the speakers, turn
counts and roles, and writes nothing. Give `--date` when you know it; without
it the file's modified time is used and recorded as such. Importing the same
file twice is refused. Then run `extract --all --project acme`.

**A recording instead of a transcript.** Give `import` a recording (m4a, mp3,
wav, ogg/opus, flac, aac, wma, or the sound track of an mp4, mov or webm) and
it becomes a one-recording session: both voices on one file. The session is written holding
the audio as 16 kHz mono WAV (decoded here, no ffmpeg needed), that copy is
uploaded to Soniox for the file pass `diarize-after` runs (paid, needs
`SONIOX_API_KEY`; their copy is deleted afterwards), and you then say who is
who with `confirm-speakers`, which deletes the session's copy. `--me` is not
used: a recording names nobody, so the first voice is taken as the
interviewer until you confirm, or `--swap`. `extract` refuses the session
until then. Without `--yes` it shows the file, its length and size and where
it would be uploaded, and writes and sends nothing. Your own file is never
touched. A file that cannot be decoded is refused before anything is
uploaded, with the ffmpeg command that converts it; a file with a few
undecodable stretches is imported with a warning saying how much was skipped.
A file over 300 minutes is refused too. If the file pass fails, the session
and its audio stay: retry with `diarize-after <session>`, or `forget` it.

The after-import steps, when the file pass needs re-running or the speakers
still need confirming:

```
python -m app fetch-voiceprint-model      # once per machine: the speaker-embedding model (about 25 MB, SHA-256 verified)
python -m app diarize-after <session>      # uploads room.wav to Soniox (paid), voiceprint cross-check
python -m app confirm-speakers <session>   # shows who said what; add --confirm (or --swap) to record it
python -m app extract <session>            # refuses until the speakers are confirmed
```

`room.wav` is the session's kept copy of the imported audio.
`confirm-speakers --confirm` deletes it. `--disputed label|voiceprint`
settles turns the voiceprint disagreed with.

An imported interview has no live record of which guide questions you asked,
so `prep` reconstructs it from the transcript: each of your turns is matched
to a guide question by the words they share, and the reason says how many
interviews were counted that way. A question asked in other words is missed
(on a set of synthetic interviews it found 52 of the 91 questions really asked), so
those counts read "at least", and a question it never finds is flagged for
you to check by hand, never moved: only interviews with a live record can say
"never asked". An interview where nothing matches the guide at all (one held
in another language than the guide, say) is left out and named as untracked.

To have the model read them instead:

```
.venv\Scripts\python.exe -m app coverage --project acme          # shows what it would send
.venv\Scripts\python.exe -m app coverage --project acme --yes    # one call, cached
```

`coverage` sends the survey and YOUR OWN turns from every interview with no
live record (never the interviewee's), asks once which guide question each
turn asks, and caches the answer in `context/coverage.json`. `prep` (and the
`author` page) then use it, labelled "from the model's reading of the
transcript", while it is fresh: a new interview, a changed survey or another
judge model makes it stale, and `prep` falls back to the word match and
says so. `prep` itself still calls no model. It stays one-way: a question the
model found counts as asked, and one it did not find is still "check by
hand", because the model's recall on real interviews is not measured.

### More commands after the call

All take `--project PATH` like the rest, and none calls a model unless noted.

- **`summary <session>`**: what one interview produced: how many claims, how
  many were stated versus inferred, and which hypotheses they bore on.
- **`standing [session]`**: where every hypothesis stands across all extracted
  interviews. Name a session to also see what that one interview moved.
- **`critique-questions <session>`**: bands YOUR OWN questions from the
  interview against the same Mom Test rubric the coach is held to, and writes
  `questions_critique.json` into the session. **This one calls the reasoning
  vendor.** `--min-words` sets the shortest turn worth judging. `--all`
  judges every interview in the project that has no critique yet (one call
  each; `--force` judges again).
- **`mirror [--show]`**: what you keep doing as an interviewer, across every
  interview in the project. A **habit** is a question flag (leading,
  hypothetical, pitching, opinion-seeking, yes/no) that shows up in two or
  more interviews; the **trend** compares your earlier interviews with your
  later ones; **walked past** lists the moments an interviewee offered
  something concrete (a specific occasion, a workaround, a cost, a pain) and
  your next question went somewhere else, marked when you said "Love it" first.
  No model call: habits come from the critiques above, walked-past from the
  transcripts. It is a detector, not a verdict: some moments will be fine.
  `--show` prints the words of each moment, to this terminal only.
- **`prep`**: the night before the next interview. Lists what you still do
  not know (a hypothesis with no decision criterion, none or only unclear
  evidence, a contested one, a thin one) with the reason for each; lists the
  holes in your opportunity tree (opportunities heard in one interview at
  most, then solutions with a mixed or thin interview signal, each with the
  tree's own next-story question; only from a current tree, otherwise it
  says to rebuild it with `/discovery:synthesize`); walks the
  guide question by question, marking the ones never reached in the
  interviews that had them; lists the topics interviewees kept raising
  without being asked that you walked past more often than you followed up
  (from `missed`'s cached grouping and judgment, naming which rule decided);
  and repeats your habits from `mirror`. No model call and nothing written: change the guide in `author`, which shows the
  same survey proposals above the survey with **Move to top**, **Remove from
  survey** and **Dismiss**. Applying one changes the survey on the page only;
  nothing is written until you press **Save survey**.
- **`prep --draft [--yes]`**: the same, plus up to two new questions for each
  gap, worded by the model in one call and printed under the gap with a
  one-line why. Without `--yes` it shows what would be sent, a few of the
  gaps and the token estimate, and calls nothing. The prompt carries the
  coach's Mom Test rubric, and a code check then drops any obvious
  hypothetical ("would you", "if we built", and their Hebrew forms), any
  question citing a gap that was not sent, a near-copy of a survey question,
  a repeat, and anything past two per gap; each drop is printed with its
  reason. Cached in `context/prep_draft.json`, keyed on the exact inputs, the
  model (`JUDGE_MODEL`) and the prompt: a re-run with nothing changed calls
  nothing. `author` offers each cached question with **Add to survey** and
  **Dismiss**; nothing is written until you press **Save survey**. Plain
  `prep` never reads the draft and still calls no model.
- **`themes`**: the patterns nobody predicted. Claims that bear on no
  hypothesis and recur in two or more interviews, grouped by the distinctive
  words they share; each group is a candidate hypothesis. No model call; reads
  claims, never quotes. `--group model` groups by meaning instead, sharing
  `missed`'s cached grouping.
- **`synthesize [--yes]`**: every interview read side by side, in one paid
  call to the judge model, and the answer is the project's opportunity
  solution tree (see "How the tree is built" below). It sends every claim
  (its text, interview id and hypothesis bearings), your hypothesis
  statements with their kind and parent, your outcome from `author` (or none:
  then the model proposes one and the tree marks it proposed) and, when an
  earlier tree exists, that tree's node labels and structure so the next one
  stays stable. Never a quote, a transcript, a falsifier or a criterion. It
  prints, indented: the outcome; each opportunity with "heard in N of M
  interviews" and single story, recurring or established; under it, its
  child opportunities and its solutions with their interview signal and
  untested assumptions; on every node the hypothesis it maps, the next story
  to ask for, its warnings and its claims grouped by interview. Then your
  hypotheses the tree does not place (a causal or pricing belief is neither
  a need nor a solution), each with how many interviews support, contradict
  or are unclear on it, the opinions and praise it heard (never nodes:
  heard, not evidence), the warnings about the whole tree (including "no
  target opportunity chosen yet": "at least 3 solutions" applies to the
  target you pick, not to every node), what changed since the previous tree
  (added, removed, moved, renamed) and what the checks dropped from the
  model's answer. Without `--yes` it shows what it would send, a few
  examples and the token estimate, and calls nothing. Cached in
  `context/synthesis.json`: a re-run with no new claims, hypotheses or
  outcome costs nothing. The hub leads with it, under "Your opportunity
  tree", drawn top-down as Torres draws it (the outcome at the top, sibling
  opportunities side by side, solutions under their opportunity; each
  branch folds, and a card's details open below it). Drag the background to
  pan; Ctrl/⌘+scroll or a trackpad pinch zooms at the cursor (plain scroll
  still scrolls the page); the −/+/Fit buttons and the arrow keys do the
  same; a minimap sits bottom-right (click it to jump); double-click an
  opportunity to fit its branch. For the interview you are viewing, each
  node is marked ▲ stronger, ▼ weaker, ◆ mixed or "new" by what that
  interview's claims did to it, and "Only what this interview changed"
  hides the rest. When claims, hypotheses or the outcome have changed since
  the build, the old tree stays on screen greyed, with a banner and
  "Copy for your agent" / "Copy as a prompt"; the hub never calls a model,
  and it re-checks when you return to its tab. In Claude Code,
  `/discovery:synthesize` shows the cost first and rebuilds on your OK; run
  from a product repository, it finds this checkout through
  `DISCOVERY_COPILOT_HOME` and stops, saying how to set it, if that is unset. An
  outline view serves narrow screens and screen readers, and filters work by
  status, solutions, warnings and words. MCP `get_synthesis` returns the
  same tree; both show the cached result and never call a model. **This one
  calls the reasoning vendor** (with `--yes`).
- **`missed`**: the topics interviewees raised unprompted in 3 or more
  interviews, and in how many you followed up ("In 7 of 12 interviews,
  interviewees raised can't carry heavy groceries without being asked. You
  followed up in 0.", from the Shmuber Eats demo). Topics that came up mostly right after you asked about
  them are listed, with counts, under "Raised when you asked". Claims are grouped by shared
  words, which misses a topic worded differently each time; `--group model`
  shows what one call to the extract model would send, and `--group model
  --yes` makes it, grouping the claims by meaning and caching the result in
  `context/topics.json`. Later runs use that cache while the claims and model
  are unchanged, and the first line of output always says which grouping was
  used. "Without being asked" is decided by word overlap between your question
  and the topic, which misses a reworded or translated guide question and every
  pitch; with `--group model --yes` a second call instead asks the model, for
  each recurring topic, whether your question right before it (and up to two
  of your questions before that, so "Anything else?" reads as continuing "What
  features would you like?") already asked about it. A pitch or leading
  question counts as asking. That call sends your own words, never the
  interviewee's; without `--yes` it shows how many of your turns and topics it
  would send, a few examples and the cost. Cached in `context/prompted.json`;
  the output always says which rule decided. "Followed up" is decided by word
  overlap too, and that is generous: a word a later question shares with the
  offer counts as a follow-up, except the next question on your guide and
  words you use in most interviews (the product's name), so a pitch that
  names the topic counts. With `--group model --yes` a third call instead
  asks the model, for each time a recurring topic came up, whether your next
  turns after it (through your second full question) followed up on it. A
  pitch or leading question does not count; a bare "What do you mean?" counts
  only as your very next turn. That call also sends your own words and the
  topic labels, never the interviewee's, and without `--yes` shows what it
  would send. Cached in `context/followed.json`; an occurrence the model left
  unanswered keeps the word rule's result and is marked.
- **`coverage [--yes]`**: which guide questions your imported (or coach-off)
  interviews really asked, read by the model once from your own turns, for
  `prep`. See "Importing past interviews". **This one calls the reasoning
  vendor** (with `--yes`).
- **`tree`**: the project's Opportunity Solution Tree (Teresa Torres). The
  outcome you set in `author` sits at the root; under it, the hypotheses you
  classified as opportunities (needs or pains heard from users), and under
  each, the solutions you hung on it. Every node shows its state and how many
  interviews support it, contradict it or were unclear, the same per-interview
  counts as `standing`. Below the tree, under "Candidate opportunities (not in
  the tree)", are the recurring `themes`. The counts update after every
  `extract`. The structure changes only when you change it: in `author`,
  classify a hypothesis or re-parent a solution, or press **Promote to
  opportunity** on a theme, which adds an empty opportunity for you to write
  (statement and falsifier, in your own words). Nothing changes until you
  press **Save hypotheses**. No model call; labels and counts, never quotes.
  Once `synthesize` has built a tree for the current claims, `tree` shows
  that tree first (statuses and counts, no claims), then your own
  classifications under "YOUR CLASSIFICATIONS", and the word-group
  candidates are left out: they are the fallback for a project with no
  synthesis.
- **`export --to backup.zip [--verify]`**: writes a checksummed copy of the
  project's irreplaceable data (transcripts, facts, hypotheses) to a zip. It
  refuses a destination git can see, so a backup can never be committed by
  accident; `--verify` re-reads every checksum after writing.

### How the tree is built

`synthesize` follows Teresa Torres's opportunity solution tree. The model
proposes the structure in one call; code decides everything else.

- **Outcome** at the root: yours from `author`, or the model's proposal,
  marked proposed until you set one.
- **Opportunities**: needs, pains and desires in the customer's first-person
  voice ("I can't tell when my build finished"), nested, each with at most
  one parent. Status is computed from the cited claims in distinct
  interviews, never claims: heard in 1 interview is a *single story*, in 2
  *recurring*, in 3 or more *established*; a parent counts its children's
  interviews too. *Well met for some* means a claim says something already
  meets the need. A claim saying an interviewee does not have the need never
  refutes it: it only shows the need is smaller.
- **Solutions** sit under exactly one opportunity, with an *interview
  signal*, never a test result: *thin* when fewer than 3 interviews touch it,
  *leaning for* when 3 or more support it and at least twice as many as
  contradict it, *leaning against* the mirror, *mixed* otherwise.
- **Assumptions** under each solution (desirability, usability,
  feasibility, viability, ethical) are the only thing ever *tested*, and
  every one starts *untested*. One with high importance and no interview
  evidence is a *leap of faith*: test it first.
- **Next story**: every node carries the next story to ask for, about past
  behaviour ("Tell me about the last time...").
- **Your hypotheses** are labels the tree reconciles against, not its
  skeleton: a node may map one, of the same kind. Opinions and praise are
  never nodes.
- **Dropped** by code, and counted: cited claims that were never sent, a
  cycle of parents, an opportunity with more than one parent, a solution
  with no valid opportunity, and any node no interview's claims support.
- **Flagged**, never dropped: not in the customer's voice, a solution or a
  metric word in an opportunity, overlapping siblings, a single child, more
  than 7 top-level opportunities, fewer than 3 solutions under an
  opportunity, a next story that is not about past behaviour.

The thresholds (1, 2, 3+ interviews; 3+ and twice the other side) are this
tool's heuristic, not Torres's: she treats sizing as judgement (see Teresa
Torres, Continuous Discovery Habits).

## The project knowledge base: everything else you already know

Interviews are not the only thing a project knows. `kb` indexes the rest —
conversations recorded elsewhere, emails, research, your own code — next to
this tool's interviews, so one search covers all of it with a citation to the
exact turn, line or paragraph.

```
python -m app kb add notes/ calls/*.vtt export.mbox ../my-product --project acme
python -m app kb add --sessions --project acme      # this project's own interviews
python -m app kb search "export by hand" --project acme
python -m app kb topics --project acme
python -m app kb list --project acme
python -m app kb remove 3f9a1c --project acme       # from the index; the file is untouched
python -m app kb digest --project acme              # what the coach digest would send; sends nothing
python -m app kb digest --yes --project acme        # summarise research and code for the coach
python -m app kb digest --show --project acme       # the notes the coach can draw on
```

| Source | Read as |
| --- | --- |
| a session folder, or `--sessions` | an interview, by role. An imported recording only after `confirm-speakers` |
| `.vtt`, `.srt`, or `.txt`/`.md` made of `Name: text` lines (Zoom, Meet, Otter, Granola exports) | a conversation, by speaker |
| `.eml`, `.mbox` (one document per message; quoted reply history dropped) | email |
| `.md`, `.txt`, `.html`, `.docx`, `.pdf` (one section per page) | research |
| a repository (a folder with `.git`, `pyproject.toml` or `package.json`) | code: its READMEs and `docs/`, plus a summary of the tree — not its source lines |

A PDF is read for its text only. A scanned PDF has no text until you run OCR
on it, and a password-protected one needs an unlocked copy. Both are skipped,
with the reason given.

- **Research by guess stays private.** A file is "research" either because you
  said so (`kb add --type research <path>`) or because nothing else fit. Only
  the first kind is ever sent to a model or returned as text to another agent:
  a call transcript saved as a PDF, a `.docx` or plain prose would otherwise
  leak someone's words. `kb add` tells you how many documents it typed by
  guess; re-add them with `--type research` once you have checked they hold no
  one else's speech. Code (repository READMEs and `docs/`) is your own and is
  used as is.
- **Secrets are refused.** Files named like credentials (`*secret*`,
  `*password*`, `.env*`, `*.pem`, `*.key`, `id_rsa`, ...) are not read, and a
  document containing a key-shaped value (an API key, a private key block, a
  `token = ...` assignment) is skipped with the reason given, never stored.
- **It stays in the folder you give it.** Hidden files, `.git`, `.venv`,
  `node_modules`, symbolic links and Windows junctions are skipped, and
  nothing outside the folder is read.

- **Local only, except `kb digest`.** Adding, searching and topics run on your
  machine and call no model. The index lives in `projects/<node>/knowledge/`, git-ignored with the
  rest of `projects/`.
- **Re-adding is safe.** An unchanged file is a no-op; a changed one replaces
  its old version.
- **Search** is keyword search (BM25) that understands Hebrew prefixes
  (`לקוח` finds `וכשהלקוחות`), final letters and plurals. `--type` narrows it.
- **Never evidence.** Other sources sit beside your interviews; they never
  count for or against a hypothesis. `standing` is the same before and after
  any `kb` command.
- **Topics** are the words and phrases each document repeats more than the
  rest of the project does, and what several documents keep returning to.
- **The coach digest** (`kb digest`) is how the live coach knows your material.
  Each research and code document is summarised into a few short notes, each
  citing its page, line or file, with one call to the extraction model per
  40,000 characters. Only new or changed documents are sent, so a second run
  costs nothing. At `start`, the notes most related to your survey, hypotheses
  and brief (up to about 4,000 characters) go into the coach's cached prompt,
  once, so nothing is added to each cycle's latency. The coach is told they are
  background, not evidence from any interview. Interviews, conversations and
  emails are never digested, and neither is research typed by guess (above):
  other customers' words never reach a live prompt. Check the list `kb digest`
  prints before `--yes`.
  A document changed or removed since the last digest is left out, and `start`
  says so.

## Before, during, after: the commands behind the chain

| Moment | What you want | Command |
| --- | --- | --- |
| The night before | what you still don't know, and what to change in the guide | `prep` |
| | everything you already know, from every source | `kb search "..."` |
| During | the whisper | `start` (coach on the console, overlay or live view) |
| After importing a recording | the evidence transcript, speakers confirmed | `diarize-after`, `confirm-speakers` |
| After one interview | its claims, and what it moved | `extract`, `summary`, `standing <session>` |
| After several | where every hypothesis stands, counted per interview | `standing` |
| | what keeps coming up that no hypothesis predicted | `themes` |
| | every interview read side by side: the opportunity solution tree, its statuses counted per interview, the next story to ask for | `synthesize`, then `tree` |
| | what you keep doing, and the offers you walked past | `critique-questions --all`, then `mirror` |

Every command above takes `--project`. Of these, only `extract`,
`critique-questions` and the live coach call a model; outside this table, so
do `kb digest`, `coverage --yes`, `synthesize --yes` and `--group model --yes`.

## Retaining the raw audio (rehearsal sessions only)

```
.venv\Scripts\python.exe -m app start --retain-audio
```

**Off by default.** Add `--retain-audio` to also write one 16 kHz mono WAV
per speaker (`interviewee.wav`, `interviewer.wav`) alongside the transcript --
for comparing speech-to-text engines on your own rehearsal recordings.

**Use `--retain-audio` for a REHEARSAL or mock interview ONLY -- never a real
customer interview.** A retained WAV pair from a real call is customer
audio on disk, one upload away from a vendor you may not have agreed to
share it with. `session.json`'s `audio_retained` field always records
whether a given session actually retained audio, so this is never left to
guesswork after the fact.

## Changing the STT engine

One environment variable, read once at startup — nothing else in the capture
or session code ever names a vendor:

```
set STT_ENGINE=soniox      REM the funded, live default
set STT_ENGINE=fake        REM offline, deterministic, no credentials -- for local testing
```

A `--engine` flag on both `start` and `precheck` overrides the environment
variable for a single run. Put `SONIOX_API_KEY` (and, if used,
`ASSEMBLYAI_API_KEY`) in a local `.env` file — never in source control.

## Troubleshooting

**Extraction failures aren't in the table below** — they're printed
CLI-side, not written as session events, and are covered in full under
"Extracting facts" above: a non-zero exit, an `unresolved-citation`
vs. `unlocatable-quote` rejection, a refusal to run at all, and the unclosed-
session warning are each a *different* condition that looks like "extraction
failed" from the terminal — that section is where you tell them apart.

Every health/trap condition is a named `event` record in `transcript.jsonl`
(and inline in `transcript.md` once rendered) — look for these names:

| Event | Meaning | What to do |
|---|---|---|
| `idle` | That stream has produced only zero-filled (synthesized) frames for a few seconds | Normal during a pause. If it never clears: check the interviewee's call app isn't muted, or that you're speaking into the right microphone |
| `recovered` | Real audio resumed after an `idle` period | Informational — no action needed |
| `lagging` | The STT engine can't keep up; the capture queue is backing up | Usually a slow local engine or a network stall. Capture is never blocked — but segments may be delayed |
| `dropped` | The queue overflowed and the oldest frame was discarded (carries a running count) | A sustained `lagging` condition turned into real data loss — switch to a faster engine (`--engine soniox`) or investigate the network |
| `device-changed` | The Windows default output device changed mid-call (e.g. headphones plugged in) | One automatic re-open is attempted; check the next event for the outcome |
| `reopened` | The automatic re-open after a `device-changed` succeeded | Informational |
| `dead` | A stream's device changed and the one re-open attempt failed | That side has stopped capturing. Restart `python -m app start` |
| `stream-failure` | An unhandled error inside one stream's worker thread | That side stopped; the other side and the session file are unaffected. Check the event's `error_type`/`message` |
| `keepalive-warning` | The silent keep-alive render stream (second layer against the silent-loopback trap) failed to open | Not fatal — the pacer's own non-blocking read is still the primary mitigation |
| `audio-retention-error` | `--retain-audio` was set but writing a WAV failed (e.g. disk full) | Retention is disabled for the rest of that session; capture and transcription are unaffected |
| `session-resumed` | `python -m app start` was pointed at an existing session directory and continued it rather than starting fresh | Informational — confirms a crash recovery picked up where it left off |
| `coverage-asked` | The coach decided your own words asked a survey question — carries which one, never the words themselves | Informational — the full history (matches AND near-misses) is what `coverage-considered` below is for |
| `coverage-considered` | A finalized interviewer segment was checked against the survey and matched nothing | Informational — normal for most of what you say |
| `coverage-queue-drop` | The coach's coverage queue was full (a sustained vendor slowdown) and the oldest pending check was dropped | Not fatal — a fresh check happens on your very next sentence |
| `reasoning-timeout` | A coach vendor call (`stage`: `coverage`, `generate` or `critique`) timed out or errored | Suggestions may be briefly missing; the transcript is completely unaffected. A single one is normal degradation — a SUSTAINED run of them (three or more in a row) is what raises the live view's own "suggestions unavailable" banner |
| `coach-cycle-skipped` | The interviewee kept talking before the previous suggestion cycle finished, so the queued-but-not-yet-started cycle was replaced by the newer one | Informational — this is "one cycle at a time, replace never queue" working as designed, not data loss |

### What a quiet suggestion region means (three different things that look identical)

"The suggestion region on the live view is quiet" is not one
condition — it is three, and only one of them is a problem:

| What you see on the live view | What it means | What to do |
|---|---|---|
| A calm banner reading **"Suggestions unavailable — transcript continues"** | The coach's reasoning layer failed a SUSTAINED run of cycles | The transcript is unaffected. Check your network and `ANTHROPIC_API_KEY`; this is never the "Transcription stopped on the laptop" banner, which is a different, more urgent condition |
| The region is quiet, **no banner at all**, everything else looks healthy | The coach had nothing worth suggesting this cycle | Nothing to do — this is a normal state, not a fault |
| **One suggestion, no alternatives underneath it** | Normal, complete state — never a partial or half-loaded render | Nothing to do |
| **The coach never suggests a hypothesis-testing question** | Two ordinary causes, both normal: (1) no hypotheses were authored for this interview — check `context/hypotheses.json` on the authoring page; (2) hypotheses exist, but nothing extracted yet is relevant enough to test one — check the post-call document's dropped candidates for whether `test_hypothesis` candidates were proposed and dropped, or never proposed at all | Author at least one hypothesis before the call if you want this move available; after the call, read the coaching summary's drop breakdown before assuming something is broken |

If you cannot immediately tell which of these three you are looking at,
that is itself worth noting after the call — see "Reading the transcript
after the call" below for where the coverage log settles any doubt about
what the coach actually did.

## Reaching the corpus from another AI agent (MCP)

`python -m app.mcp` serves this machine's interview corpus to your other AI
agents over the Model Context Protocol — JSON-RPC 2.0 on stdio, hand-rolled
against the standard library, no new dependency.

**What it will and will not hand over.** It is READ-ONLY: seven tools, none of
which writes a byte. It exposes extracted CLAIMS, hypothesis standings and
interview metadata — never `quoted_text`, never a transcript segment, never
audio. This is the only surface in this project that hands the corpus to a
process you did not write, so the quote boundary is enforced structurally
(every projection is written out field by field) and pinned by a test.

**Never put a key in an MCP config.** These files get committed. This server
needs no credential of any kind — it reads local files.

### Claude Code

Nothing to do — `.mcp.json` at the repository root registers it, and Claude
Code offers to enable it the first time you open this folder:

```json
{
  "mcpServers": {
    "discovery-copilot": {
      "type": "stdio",
      "command": ".venv/Scripts/python.exe",
      "args": ["-m", "app.mcp"]
    }
  }
}
```

The interpreter path is **relative on purpose**, so it is the venv of
whichever checkout you opened — including a git worktree. Never replace it
with an absolute path: that works in exactly one checkout on one machine.
Claude Code launches the server with the project directory as its cwd, which
is also what puts the repository root on `sys.path` so `-m app.mcp` can import
`app`.

Check it with `/mcp` inside Claude Code; the server should list as
`discovery-copilot` with seven tools.

### Claude Desktop

Claude Desktop reads ONE global config instead of a per-repository file, and
it launches servers from an arbitrary working directory. So the entry needs an
**absolute** interpreter path and an explicit **cwd** — without the cwd,
`python -m app.mcp` cannot import `app` and the server dies at startup with an
import error you will only see in Claude Desktop's own log.

Edit `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and add:

```json
{
  "mcpServers": {
    "discovery-copilot": {
      "command": "C:\\path\\to\\product-discovery-agent\\.venv\\Scripts\\python.exe",
      "args": ["-m", "app.mcp"],
      "cwd": "C:\\path\\to\\product-discovery-agent"
    }
  }
}
```

Replace both paths with your own checkout, restart Claude Desktop, and the
tools appear under the connector menu.

### Another repository: the `discovery` Claude Code plugin

`.mcp.json` reaches the server only from inside this checkout. A product
repository opened in Claude Code gets it from the plugin in
`integrations/claude-code/`, which teaches that repository three things: the
tools (the server registration), which project it answers to
(`.discovery-copilot.json`, written by `/link-discovery`), and how to reason with
the evidence (the `discovery-evidence` skill: `demo` and `undeclared` claims are
never findings, counts are per interview, gaps become proposals rather than
assumptions).

Once per machine:

```
setx DISCOVERY_COPILOT_HOME "C:\path\to\product-discovery-agent"
claude plugin marketplace add "C:\path\to\product-discovery-agent\integrations\claude-code"
claude plugin install discovery@discovery-copilot-local
```

Then restart Claude Code, and in each product repository run
`/discovery:link-discovery <project>`. After that, `/discovery:evidence
<question>` answers from the interviews with citations, and
`/discovery:interview-gap` drafts hypotheses and survey questions into the
product repository's `discovery-proposals.md`, which you enter here through
`author`. `/discovery:synthesize` rebuilds the opportunity tree from this
checkout (found through `DISCOVERY_COPILOT_HOME` when you run it from a product
repository) after showing the cost and getting your OK. Nothing else in the plugin
writes to this checkout.

- **The checkout is named only through `DISCOVERY_COPILOT_HOME`.** Claude Code
  copies an installed plugin into its own cache, so no relative path can
  reach this checkout, and an absolute one would be the `open-console.bat`
  mistake. The same copy means **an edit to the plugin reaches nobody until
  `claude plugin marketplace update discovery-copilot-local`** and a restart.
- **`/link-discovery` also writes deny rules** into the product repository's
  `.claude/settings.local.json` for this checkout's `projects/`, `sessions/`
  and `context/`. Measured, not assumed: without them, a session in the product
  repository read a transcript here directly, around everything the MCP
  server withholds. With them, the same read was refused. Claude Code asks
  before writing its own settings file; approve it.


### The twelve tools

| Tool | Answers |
| --- | --- |
| `list_projects` | every project node on this machine — start here |
| `get_survey` | the ordered questions you set out to ask |
| `get_hypotheses` | statements, falsifiers, states, decision criteria |
| `list_interviews` | which interviews exist, and whether each closed cleanly |
| `get_facts` | the extracted claims and which way each one bears |
| `get_standing` | where each hypothesis stands, counted per INTERVIEW |
| `get_interview_summary` | what one interview did, deterministically |
| `search_knowledge` | cited hits from the project knowledge base; text only for research and code, never for speech |
| `get_mirror` | your habits as an interviewer across interviews: flags, trend, walked-past moments (no words) |
| `get_themes` | claims no hypothesis predicted that recur across interviews (claims, never quotes) |
| `get_tree` | the opportunity solution tree: the synthesized one when fresh, plus your own classifications (outcome, opportunities, solutions, per-interview counts); candidate themes only when there is no synthesis (labels and counts only) |
| `get_synthesis` | the cached `synthesize` tree: outcome, nested opportunities, solutions and assumptions with code-computed statuses, each node's claims grouped by interview, unplaced hypotheses, opinions, warnings and the diff against the previous tree (claims, never quotes; never calls a model) |

### `scope`: one node, or a whole sub-tree

`get_hypotheses`, `list_interviews`, `get_facts`, `get_standing` and
`get_interview_summary` take a `scope`:

- `"node"` (the default) reads only the project you named.
- `"subtree"` also reads every project nested underneath it and merges the
  results.

`subtree` is opt-in and never implicit, because it is a cross-project read —
the same rule the console's "draw on another project's knowledge" follows:
**reads may merge, within one hierarchy, on explicit request; writes never
merge.** A sub-tree never climbs to a parent, never reaches a sibling, and
never reaches another hierarchy — asking for `acme` does not pull in
`acme-corp`.

Every item in a merged answer carries the `project` node it came from, and
every count in a merged answer is **per-interview, never per-fact**: one
interviewee who made the same point five times moves `supporting_interviews`
by one. `supporting_facts` is reported alongside it, so you can see both
numbers and never mistake one for the other. If one node in the sub-tree has a
malformed artifact, only that node degrades — its path is named in `errors`
and the rest of the answer still arrives.
