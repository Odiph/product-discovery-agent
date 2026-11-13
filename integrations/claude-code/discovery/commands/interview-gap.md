---
description: Find what the interviews have not yet tested, and draft hypotheses and questions for the next interview
argument-hint: [optional focus, e.g. a feature or decision]
---

Find the gaps in this product's interview evidence and draft what to learn
next. Focus, if given: $ARGUMENTS

Follow the `discovery-evidence` skill. Read `.discovery-copilot.json` first. If
it is missing, call `list_projects`: when every project there has
`corpus: demo` (a first run after `/start`), use that project, and say on
every result that it comes from mock interviews, not real users. Otherwise
stop and suggest `/link-discovery`.

1. Read `get_standing`, `get_hypotheses`, `get_survey` and `list_interviews`
   for the linked project and scope. Also read `get_themes` (claims no
   hypothesis predicted, recurring across interviews: each is a candidate
   hypothesis) and `get_mirror` (the interviewer's own habits and the offers
   they walked past: say which to avoid next time).
2. List the gaps, most decision-relevant first:
   - hypotheses with no interviews bearing on them, or only unclear ones;
   - hypotheses with `is_scorable: false`, which need a decision criterion
     before any count means anything;
   - interviews not yet extracted (`unextracted_projects`), which are free
     evidence waiting on one command: `python -m app extract --project <path>
     <session_id>`, run from the Product Discovery Agent checkout;
   - with a focus given, parts of it no hypothesis covers.
3. Draft proposals for the biggest gaps, following the skill's section 5:
   hypotheses with a falsifier and a decision criterion, and survey questions
   about past behaviour. Keep it short: three hypotheses and six questions at
   most.
4. Append them to `discovery-proposals.md` under today's date, and tell the
   operator they go in through `python -m app author --project <path>` in the
   Product Discovery Agent checkout. Do not write to the Product Discovery Agent yourself.
5. Mention that `python -m app prep --project <path>`, run in the Discovery
   Copilot checkout, prints the same gaps against the guide question by
   question, with no model call.
