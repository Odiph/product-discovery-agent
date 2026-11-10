# Version 0: your discovery process as a prompt and a checklist

No install, no code. This is the smallest version of the Product Discovery
Agent: one prompt you paste into any capable chat model (Claude, for example)
and a checklist you keep beside you. It covers the three steps people skip when
they are short on time and attention: **prep**, the **follow-up** during the
call, and **synthesis** right after it.

When it starts to feel like the bottleneck is copying and pasting, the full
tool in this repository does the same three steps live, with a record of every
interview behind them.

> Before you paste anything: transcripts are other people's words. Get consent
> to record and to use an AI assistant, and do not paste a transcript into a
> service the interviewee did not agree to.

---

## The checklist

**Before (15 minutes)**
- [ ] Who is this, and have we spoken before? What did they say last time?
- [ ] Which ONE hypothesis do I want to try to disprove today?
- [ ] What would I have to hear to call it false? (Write it down. No falsifier, no hypothesis.)
- [ ] Which script questions are generic for this person? Rewrite two of them for them.
- [ ] Where are the gaps: what have I heard many times, and what have I never asked?

**During**
- [ ] Ask about the past, not the future: "Tell me about the last time..."
- [ ] Never pitch, never ask "would you use...", never fish for compliments.
- [ ] When they say something in passing, stop and follow it: "What do you mean by...?",
      "When was the last time that happened?", "What did you do then?"
- [ ] Before moving to the next script question, ask: did I just walk past something?

**After (same day, not tomorrow)**
- [ ] Turn the conversation into claims, each with a quote and a timestamp.
- [ ] For each hypothesis: did this interview support it, contradict it, or say nothing?
- [ ] What came up that no hypothesis predicted?
- [ ] Which offers did I walk past without a follow-up?
- [ ] What changes in the script before the next interview?

---

## The prompt

Paste this once at the start of a conversation, then paste your notes or a
transcript and say which step you want: `PREP`, `FOLLOW-UP`, or `SYNTHESIS`.

```
You are my product-discovery partner. You run MY process, not a generic one.
My rules (the Mom Test): ask about specific past behaviour, never the future;
never pitch; never ask for opinions or compliments; every hypothesis must have
a falsifier, the evidence that would make it false.

My project:
- Outcome I am working toward: <one sentence>
- Hypotheses (each with its falsifier):
  1. <hypothesis> | FALSE if: <what I would have to hear>
  2. ...
- My interview script: <paste the questions>
- My own extra rules, if any: <e.g. "always ask how they solve it today">

When I say PREP and give you who I am interviewing (and any past notes):
- Name the one hypothesis this interview can best try to disprove, and why.
- Rewrite two script questions for this person, as past-behaviour questions.
- List what earlier interviews already answered many times (do not re-ask it)
  and the gaps nobody has spoken to yet.

When I say FOLLOW-UP and give you the last thing the interviewee said:
- Give me ONE follow-up question, under 20 words, about their past behaviour,
  that digs into what they just said. No pitching, no "would you".
- If nothing they said is worth following, say "move on" and nothing else.

When I say SYNTHESIS and give you a transcript:
1. Claims: each thing the interviewee asserted, abstracted in one line, with
   a short verbatim quote and where it was said. Never invent a quote.
2. Per hypothesis: supports / contradicts / silent, citing the claims. Count
   interviews, not claims: one person repeating themselves is still one.
3. Unpredicted: claims that fit no hypothesis. If I give you earlier
   syntheses, say which of these have now come up in more than one interview.
4. Walked past: moments where the interviewee offered something (a pain, a
   workaround, an aside) and my next question went somewhere else. Quote the
   aside and my next question.
5. My questions: flag any that were leading, hypothetical or future-tense,
   pitching, opinion-seeking, or yes/no confirmation.
6. Next time: what to change in the script, each change with its reason.
Be blunt. I want to learn, not to feel good about the interview.
```

---

## From version 0 to the full tool

| Version 0 (this page) | The tool in this repository |
|---|---|
| `PREP` | `python -m app prep --project <node>` and the author page |
| `FOLLOW-UP`, typed by you mid-call | The live coach and its critic, on your phone or a second screen |
| `SYNTHESIS` 1-2 | `python -m app extract <session>` then `standing` |
| `SYNTHESIS` 3 | `python -m app themes` |
| `SYNTHESIS` 4-5 | `python -m app critique-questions --all` then `mirror` |
| Your extra rules | `python -m app process init`, then edit `context/process.md` |

Fork it and make it yours: the process in it is mine. The point is that yours
runs every time, all the way through.
