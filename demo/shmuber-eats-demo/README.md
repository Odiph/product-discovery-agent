# Shmuber Eats beta interviews (SYNTHETIC demo dataset)

**Everything in this folder is invented.** Shmuber Eats is a fictional product,
and none of this is real customer speech: the households, their names, their
jobs and every line they say are fiction. Stores are named only by generic words
(the big supermarket, the discount place, the market). The transcript files
carry no header line (the parser would read one as a turn), so this README is
where their provenance is recorded.

## The story

**Shmuber Eats (demo project)** is a grocery delivery app. A household orders
from a local supermarket, a picker shops the order, and it arrives in a two-hour
window the same day or the next. The beta runs in one metro area. Many
households place a first order, but fewer than one in three place a second
within 30 days. The outcome the team is after: **more households place a second
order within 30 days.**

The team's bet (h1): surprise substitutions at the door are why first-timers
don't come back. Their other bets are a push notification to approve swaps
(h2, the solution to h1), two-hour windows that don't fit working days (h3), a
shared household list (h4) and a 9.99 a month delivery pass (h5).

The team ran 12 interviews. They felt great. Everyone was friendly, had a
small swap story, and had an opinion about the pass. But the interviewer came
unprepared, stuck to the generic guide, and almost never followed up:
"Great, great. Let's move on."

In 8 of the 12 interviews, the interviewee mentions **in passing** that their
first order was set off by a one-off situation: a child with a fever, a car in
the garage, the week of a house move, a work deadline, a sprained ankle, a
newborn, a snowstorm, cousins arriving for dinner that night. Once it passed,
they went back to their usual store. Every time, the next interviewer turn
moves on to a guide question that ignores it. No hypothesis predicted it, and it
quietly undercuts the substitution bet: most of these households were never
trying to change how they shop, so a better swap flow would not have brought
them back. The wording differs every time, so no single keyword finds all 8.

Two control topics make a "what did we miss" detector earn its answer:

- **Control A, followed up.** In 5 interviews the interviewee volunteers that
  the picker's replacement was wrong for what they were cooking (a coconut
  drink for curry, cake flour for pizza dough, spicy tortillas for four-year-olds,
  margarine for buttercream, smoked salmon slices for a baked fillet). The
  interviewer follows up every time. A correct detector must not flag it as
  missed.
- **Control B, below the noise floor.** The app logging the interviewee out at
  checkout comes up in only 2 interviews. A detector with a 3-interview floor
  must not surface it.

`GROUND-TRUTH.json` (rendered as `GROUND-TRUTH.md`) records, per interview, each
planted line, its turn number, the interviewer's next line, and whether it was
followed up. It is also the answer key for "without being asked": which guide
questions the interviewer really asked (by turn), where they pitched a topic,
and, for every mention of substitutions, the delivery window and the pass
price, whether it answered a question or pitch about it. Substitutions (24
mentions) and the pass price (23) are always prompted; the delivery window is
volunteered twice in 22; every planted aside and control line is volunteered.
The interviewer asked 115 of the 120 guide questions and made 11 pitches,
among them "Wouldn't it be great if we texted you before swapping anything?"
in 06. The rules it follows are in its `prompted_policy`.

## Contents

```
transcripts/NN-<name>.txt   12 interviews, `Name HH:MM:SS: text`, one turn per line
context/brief.json          what the team knew going in
context/survey.json         the generic interview guide (s1..s10)
context/hypotheses.json     the team's bets, each with a falsifier and a criterion
GROUND-TRUTH.json / .md     where the signal and the controls are planted, and the unplanted theme
seed/                       this project already processed (see below)
```

The transcripts are in English, in a natural spoken style. Each has 42-52 turns
and runs 15-23 minutes. The interviewer is always labelled `Interviewer`, and
each interviewee by first name. All 12 files parse with
`app.kb.spoken.from_speaker_text`, with one turn per line.

## Loading it

From the repository root (PowerShell). The project folder is git-ignored, so
this sets it up locally:

```
mkdir projects\shmuber-eats-demo\context
copy demo\shmuber-eats-demo\context\*.json projects\shmuber-eats-demo\context\
'{"corpus": "demo", "note": "SYNTHETIC mock interviews"}' | Set-Content projects\shmuber-eats-demo\project.json

python -m app import demo/shmuber-eats-demo/transcripts --project shmuber-eats-demo --me Interviewer --date 2026-11-02 --yes
python -m app extract --all --project shmuber-eats-demo --yes           # 12 model calls
python -m app critique-questions --all --project shmuber-eats-demo      # 12 model calls
python -m app missed --project shmuber-eats-demo --group model --yes    # 2 model calls, then cached
python -m app coverage --project shmuber-eats-demo --yes                # 1 model call, then cached
python -m app prep --project shmuber-eats-demo
python -m app standing --project shmuber-eats-demo
python -m app mirror --project shmuber-eats-demo
python -m app tree --project shmuber-eats-demo
```

Leave out `--yes` on `import`, `extract --all`, `missed --group model` and
`coverage` to see what each would do and what it would send, without doing it.
`missed --group model --yes` makes two calls: one grouping the claims, one
judging, from your own turns only, whether each topic was already asked
about. `coverage --yes` reads which guide questions each interview asked, for
`prep`.

Set `JUDGE_MODEL` in `.env` to a strong model for the two judgments over your
own turns; a weak judge moves topics between "asked" and "not asked" from one
run to the next.

## What the tool reported

One paid run on 2026-11-17: extraction and the topic grouping by
`google/gemini-2.5-flash`, the two judgments and `coverage` by
`anthropic/claude-sonnet-5.5`. Against the answer key:

| Topic | `missed` reported | Answer key |
|---|---|---|
| Can't carry heavy groceries | 7 of 12, followed up in 0 (the headline) | 6 of 12, followed up in 0 (not planted, see below) |
| Orders during emergencies (the planted one-off first order) | 6 of 12, followed up in 1 | 8 of 12, followed up in 0 |
| Prefers shopping in person | 5 of 12, followed up in 0 | not keyed |
| Inaccurate substitutions (Control A) | 6 of 12, followed up in 6 | 5 of 5, all followed up |
| App logs out during order (Control B) | 3 of 12, followed up in 0 | 2 of 12 |
| Delivery window inconvenient | 3 of 12, followed up in 1 | volunteered twice |

**The headline is a theme nobody planted.** Six households say, unprompted,
that not hauling water, rice or bags is what they value (02, 03, 07, 09, 11,
12). The authoring left it in, the model found it, and it is now keyed in
`GROUND-TRUTH.json` as `carrying_heavy_shopping`. Two of those lines (02's car
in the garage, 07's sprained ankle) are also planted one-off asides, told as "I
couldn't carry it home", so the model filed them under carrying, and 10's
snowstorm went there too. That is why the planted signal reads 6, not 8: it
caught 01, 04, 05, 08 and 12, counted 11 (who tried it because her daughter
asked her to), and read one of 12's next turns as a follow-up. Read together,
the top three topics still tell the story the team missed: people ordered when
something stopped them carrying their shopping home, then went back to the
store they prefer.

Control A came through as intended: followed up every time, so it stays out
of "missed". Control B did not: the model grouped 08's "the app forgot my
basket" with the two logouts, which lifts it to 3 and over the floor.
Substitutions and the pass price stayed out of the headline. `coverage` found
115 of the 115 guide questions asked, and none that were not. `prep` puts
carrying, emergencies and shopping in person at the top of "what they keep
raising that you did not ask about".

## The seed: the same project, already processed

`seed/` is this project after `import`, `extract --all`, `critique-questions
--all`, `missed --group model --yes` and `coverage --yes`, from the run above:
the claims, the question critiques, the topic grouping, the two cached
judgments and the coverage reading, plus the team's outcome and one
`synthesize` (claude-sonnet-5.5, about 2 minutes), so the hub opens on an
opportunity tree. Its `project.json` pins the models those caches were made
with (`"models"`), so they stay fresh whatever your `.env` configures. Like
everything here, it is synthetic.

The tree reads the planted signal better than `missed` does: one opportunity,
"When illness, a newborn, an injury or bad weather keeps me from getting out,
I need food brought to me", is heard in 8 of 12 interviews, exactly the
answer key's count. Substitutions lead it (heard in 11 of 12), and the team's
push-notification solution comes out leaning against (for in 2, against in 9).
