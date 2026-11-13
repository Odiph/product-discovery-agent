---
description: First run. See what the interview tool does, on mock interviews if you have none yet, and get the one next step
---

Get this user from "just installed the plugin" to a real answer, or to one
concrete next step. Never end on a raw error.

Follow the `discovery-evidence` skill throughout.

1. Call `list_projects`. If the call fails, the MCP server is not connected:
   say so, point to the plugin's install line in the repository README
   ("Claude Code plugin"), and stop there.
2. If the response has a top-level `hint`, there is no project yet. Run
   `python -m app demo --yes` from the interview tool's checkout. You may do
   this without asking: it makes no API call, needs no key, and writes only
   its own `projects/claudictive-beta` folder. Anything that costs money
   still asks first. Then call `list_projects` again.
3. If the only project has `corpus: demo`, walk the user through it. Start
   with: "These are 12 mock interviews, not real users." Then show what the
   tool finds: where the hypotheses stand (`get_standing`, through the
   evidence skill), and the topics interviewees kept raising that were not
   followed up, by running `python -m app missed --project claudictive-beta --group model`
   from the checkout (free: it reads cached results and calls no model; no
   MCP tool returns it). Say on every result that it comes from mock
   interviews.
   Never report a demo result as a finding about real users.
4. If a project carries a `hint`, give that hint as the single next step,
   word for word. One step, not a list.
5. If the user has a real (non-demo) project and this repository has no
   `.discovery-copilot.json`, the next step is `/link-discovery`. Never write
   that file without asking; it changes the user's repository.
6. End with three first prompts that work right now:
   - `/evidence use during game downtime`
   - `/interview-gap`
   - "What does the mirror say about my questions?"
