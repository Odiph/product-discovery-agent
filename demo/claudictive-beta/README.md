# Claudictive beta interviews (SYNTHETIC demo dataset)

**Everything in this folder is invented.** It was written for a conference talk
demo. None of it is real customer speech: the interviewees, their names, their
jobs and every line they say are fiction. Real game titles appear only as the
games the fictional people play. The transcript files carry no header line
(the parser would read one as a turn), so this README is where their
provenance is recorded.

## The story

A founder built **Claudictive**, an Overwolf in-game overlay that lets a gamer
talk to Claude Code without leaving the game. The bet: gamers want to work with
Claude *in the heat of the match*, at the press of a button.

Beta users installed it, but usage was low, so the founder ran 12 user
interviews. They felt great. Everyone was friendly, loved the idea and asked
for features (voice input, a smaller window, themes, a mobile companion app).
But the founder came unprepared, stuck to a generic script, and almost never
followed up: "מעולה, מעולה. בוא נעבור לשאלה הבאה."

In 8 of the 12 interviews, the interviewee mentions **in passing** the dead time
between rounds and matches (matchmaking queue, loading screen, lobby, waiting to
respawn, picking phase, warmup) as the moment they actually talk to Claude, or
already alt-tab to check things. Nobody wants it mid-fight. The one person who
tried it mid-round died in two seconds. Every time, the next interviewer turn
moves on to a scripted question that ignores the aside. No hypothesis predicted
it. The founder's in-match bet was wrong from day one, and the evidence was in
the room.

Two control topics make a "what did we miss" detector earn its answer:

- **Control A, followed up.** The overlay window covering part of the HUD
  (minimap, kill feed, hotbar) comes up in 5 interviews, and the interviewer
  follows up every time. A correct detector must not flag it as missed.
- **Control B, below the noise floor.** The default hotkey colliding with another
  binding comes up in only 2 interviews. A detector with a 3-interview floor
  must not surface it.

`GROUND-TRUTH.json` (rendered as `GROUND-TRUTH.md`) records, per interview, each
planted line, its turn number, the interviewer's next line, and whether it was
followed up. It is also the answer key for "without being asked": which guide
questions the interviewer really asked (by turn), where they pitched a topic,
and, for every mention of voice input, themes and price, whether it answered
a question or pitch about it. Voice (21 mentions) and price (21) are always
prompted; themes is volunteered twice in 14; every planted aside and control
line is volunteered. The rules it follows are in its `prompted_policy`.

## Contents

```
transcripts/NN-<name>.txt   12 interviews, `Name HH:MM:SS: text`, one turn per line
context/brief.json          what the founder knew going in
context/survey.json         the generic interview script
context/hypotheses.json     the founder's bets, each with a falsifier
GROUND-TRUTH.json / .md     where the signal and the controls are planted
```

The transcripts are mostly Hebrew with English tech and game terms mixed in
mid-sentence. Two (05, 10) are mostly English. Each has 46-56 turns and runs
15-23 minutes. The interviewer is always labelled `Interviewer`, and each
interviewee by first name. All 12 files parse with
`app.kb.spoken.from_speaker_text`, with one turn per line.

## Loading it

From the repository root (PowerShell). The project folder is git-ignored, so
this sets it up locally:

```
mkdir projects\claudictive-beta\context
copy demo\claudictive-beta\context\*.json projects\claudictive-beta\context\
'{"corpus": "demo", "note": "SYNTHETIC mock interviews"}' | Set-Content projects\claudictive-beta\project.json

python -m app import demo/claudictive-beta/transcripts --project claudictive-beta --me Interviewer --date 2026-06-15 --yes
python -m app extract --all --project claudictive-beta --yes           # 12 model calls
python -m app critique-questions --all --project claudictive-beta      # 12 model calls
python -m app missed --project claudictive-beta --group model --yes    # 2 model calls, then cached
python -m app coverage --project claudictive-beta --yes                # 1 model call, then cached
python -m app prep --project claudictive-beta
python -m app standing --project claudictive-beta
python -m app mirror --project claudictive-beta
python -m app tree --project claudictive-beta
```

Leave out `--yes` on `import`, `extract --all`, `missed --group model` and
`coverage` to see what each would do and what it would send, without doing it.
`missed --group model --yes` makes two calls: one grouping the claims, one
judging, from your own turns only, whether each topic was already asked
about. `coverage --yes` reads which guide questions each interview asked, for
`prep`; `python -m benchmark.coverage_recall projects/claudictive-beta` then
scores that reading against the answer key.

Set `JUDGE_MODEL=anthropic/claude-sonnet-5.5` (or another strong model) in
`.env` for the two judgments over your own turns: on `gemini-2.5-flash` the
prompted judgment moved the dead-time topic from 7 interviews to 3 between two
runs of the same prompt.

What to expect, and how close the tool gets to the ground truth above, is in
`GROUND-TRUTH.md`. On 2026-11-11, judged by Sonnet 5.5, `missed` reported the
dead-time topic in 9 of 12 interviews with 1 follow-up against a ground truth
of 8 and 0. The model grouping merged one unrelated claim into the topic, and
the word-based follow-up judge counts 05's pitch ("talk to Claude in the
middle of a match?" shares "match" with the topic) as a follow-up. The
followed-up control scored 5 of 5, and the guide's own questions (voice,
price) dropped out of the headline. `coverage` found all 109 guide questions
asked, and `prep` lists the dead time as a topic to add to the guide.

## The seed: the same project, already processed

`seed/` is this project after `import`, `extract --all`, `critique`, and
`missed --group model --yes`: the claims, the topic grouping and the two cached
judgments. `python -m app demo --yes` copies it into `projects/claudictive-beta`,
so the headline above shows with no API call and no key. Its `project.json`
pins the models those caches were made with (`"models"`), so they stay fresh
whatever your `.env` configures. The `extract` pin covers the topic grouping;
re-running extraction itself still uses your own `EXTRACT_MODEL`. Like
everything here, it is synthetic.
