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
followed up.

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
python -m app missed --project claudictive-beta --group model --yes    # 1 model call, then cached
python -m app standing --project claudictive-beta
python -m app mirror --project claudictive-beta
python -m app tree --project claudictive-beta
```

Leave out `--yes` on `import`, `extract --all` and `missed --group model` to see
what each would do and what it would send, without doing it.

What to expect, and how close the tool gets to the ground truth above, is in
`GROUND-TRUTH.md`. On 2026-11-11 `missed` reported the dead-time topic in 9 of
12 interviews with 1 follow-up against a ground truth of 8 and 0: the model
grouping merged one unrelated claim into the topic.
