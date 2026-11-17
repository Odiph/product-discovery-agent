---
description: Rebuild the opportunity solution tree from every interview (one paid model call)
argument-hint: [project path]
allowed-tools: Bash(printenv DISCOVERY_COPILOT_HOME)
---

Rebuild this product's opportunity solution tree from every interview. Project,
if given: $ARGUMENTS

Follow the `discovery-evidence` skill. Read `.discovery-copilot.json` first. If
it is missing, call `list_projects`: when every project there has
`corpus: demo` (a first run after `/start`), use that project, and say on
every result that it comes from mock interviews, not real users. Otherwise
stop and suggest `/link-discovery`.

The rebuild runs from the Product Discovery Agent checkout (the folder with
`app/synthesis_cli.py`), which is not where you are when the hub sent you here
from a product repository. Find it once, before step 1:

- If the current folder already has `app/synthesis_cli.py`, use it.
- Otherwise read `DISCOVERY_COPILOT_HOME` with the Bash tool, exactly
  `printenv DISCOVERY_COPILOT_HOME` (`echo %DISCOVERY_COPILOT_HOME%` in a
  Windows command prompt), and use that folder.
- If neither applies, stop and say how to set it: point `DISCOVERY_COPILOT_HOME`
  at the checkout (`setx DISCOVERY_COPILOT_HOME "C:\path\to\discovery-copilot"`
  on Windows, then restart Claude Code), or run this from the checkout itself.

Run both `python -m app synthesize` invocations below with that folder as the
working directory.

1. Run `python -m app synthesize --project <path>` from the checkout WITHOUT
   `--yes`. It calls nothing: it prints what would be sent and the cost
   estimate. Show the user that cost and ask for their OK. If it says the
   cached tree is still current, say a re-run costs nothing and stop.
2. Only on their OK, run the same command with `--yes`, from the checkout.
   This is one paid call to the reasoning vendor. Never add `--yes` without
   the OK in this conversation.
3. Read `get_synthesis` for the project and summarise its stored `diff` in at
   most eight lines, from exactly its four lists and then the top-level
   `warnings`: `added` and `removed` nodes (kind and statement), `moved` (before
   parent -> after parent), `renamed` (before -> after statement). Report only
   what the stored diff records; never infer status or signal changes. Mock
   interviews are labelled as such.
4. Tell them the hub refreshes when they return to its tab, and that the
   greyed tree with a banner is replaced by the new one.

Never edit the tree or its cache (`context/synthesis.json`) by hand.
