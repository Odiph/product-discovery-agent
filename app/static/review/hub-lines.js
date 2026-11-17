// The bottom line each hub section opens with, and the counts on the nav.
//
// Pure functions of the payloads the sections already draw from: no fetch, no
// DOM, no model. `hub-nav.js` hands each one the same object the section was
// rendered from, so a number here can only disagree with the section if the
// arithmetic does, and `hub_lines.test.mjs` / `hub_nav.test.mjs` check both.
// Where a section has nothing to show, its line says so in words.
(function () {
  "use strict";

  // The same labels `review.js` draws the mirror's rows with; a test pins the
  // two tables equal so a rename cannot leave the bottom line behind.
  var MIRROR_FLAGS = {
    leading: "leading",
    hypothetical_or_future_tense: "hypothetical / future",
    pitch: "pitching",
    opinion_seeking: "opinion-seeking",
    confirmation_only: "yes/no confirmation",
    off_topic: "off-topic"
  };
  var SHORT = 48;

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function num(value) { return typeof value === "number" ? value : 0; }

  /** A statement short enough to sit inside a sentence, cut at a word. */
  function shortStatement(text) {
    var s = String(text || "").trim();
    if (s.length <= SHORT) { return s; }
    var cut = s.lastIndexOf(" ", SHORT);
    return s.slice(0, cut > 0 ? cut : SHORT).replace(/[\s,;:.]+$/, "") + "…";
  }

  function quoted(standing) { return "“" + shortStatement(standing.statement || standing.id) + "”"; }

  var STANDING_KINDS = [
    ["contested", "contested", "are contested"],
    ["onlyFor", "only supported", "are only supported so far"],
    ["onlyAgainst", "only undermined", "are only undermined so far"],
    ["none", "with no directed evidence yet", "have no directed evidence yet"]
  ];

  function standingKind(s) {
    var f = num(s.supporting_interviews), a = num(s.contrary_interviews);
    if (f && a) { return "contested"; }
    if (f) { return "onlyFor"; }
    return a ? "onlyAgainst" : "none";
  }

  function tallyClause(list) {
    var counts = {};
    list.forEach(function (s) { var k = standingKind(s); counts[k] = (counts[k] || 0) + 1; });
    var present = STANDING_KINDS.filter(function (k) { return counts[k[0]]; });
    if (present.length === 1 && list.length > 1) { return "All " + list.length + " hypotheses " + present[0][2] + "."; }
    return "Of " + plural(list.length, "hypothesis", "hypotheses") + ": "
      + present.map(function (k) { return counts[k[0]] + " " + k[1]; }).join(", ") + ".";
  }

  function mostUndermined(list) {
    var top = null;
    list.forEach(function (s) { if (num(s.contrary_interviews) > (top ? num(top.contrary_interviews) : 0)) { top = s; } });
    if (!top) { return null; }
    return "Most undermined: " + quoted(top) + ", " + plural(num(top.supporting_interviews), "interview", "interviews")
      + " for, " + num(top.contrary_interviews) + " against.";
  }

  function ruleClause(list) {
    var missing = list.filter(function (s) { return !s.is_scorable; });
    if (!missing.length) { return null; }
    if (missing.length === list.length) { return list.length === 1 ? "It has no decision rule yet." : "None has a decision rule yet."; }
    return missing.length === 1 ? quoted(missing[0]) + " has no decision rule yet."
      : missing.length + " have no decision rule yet.";
  }

  function movedClause(list) {
    var moved = list.filter(function (s) { return s.moved_this_interview; });
    if (!moved.length) { return "This interview moved none of them."; }
    if (moved.length === 1) { return "This interview moved " + quoted(moved[0]) + "."; }
    return moved.length === list.length ? "This interview moved all " + list.length + "."
      : "This interview moved " + moved.length + " of them.";
  }

  function standings(list, session) {
    if (!list || !list.length) { return "No hypotheses written for this project yet."; }
    var parts = [tallyClause(list), mostUndermined(list), ruleClause(list)];
    if (session) { parts.push(movedClause(list)); }
    return parts.filter(Boolean).join(" ");
  }

  function proposals(data, list) {
    if (!data) { return "The proposals could not be loaded."; }
    var items = data.proposals || [];
    if (!items.length) { return "This interview proposed no state changes."; }
    var byId = {};
    (list || []).forEach(function (s) { byId[s.id] = s; });
    var named = items.slice(0, 2).map(function (p) {
      var s = byId[p.target_hypothesis_id];
      return (s ? quoted(s) : p.target_hypothesis_id) + " to " + p.proposed_state;
    });
    if (items.length > 2) { named.push("and " + (items.length - 2) + " more"); }
    var line = (items.length === 1 ? "1 proposed state change waits" : items.length + " proposed state changes wait")
      + " for your decision: " + named.join(", ") + ".";
    var declined = items.filter(function (p) { return p.previously_declined; }).length;
    return declined ? line + " You declined " + declined + " of them before." : line;
  }

  function addHypothesis(list) {
    var n = (list || []).length;
    if (!n) { return "No hypotheses yet. Add the belief you most need to test."; }
    return "You have " + plural(n, "hypothesis", "hypotheses") + ". Add one with the rule that would decide it.";
  }

  // Where an interview's coverage came from (`review_coverage.py`). Only a
  // LIVE record can make silence mean "never asked"; the other three are
  // one-way, as in `prep`: a hit counts, silence is "check by hand".
  var READ_AS = { model: "read from the transcript by the model", words: "matched by words" };
  var UNREAD = [["model", "read by the model"], ["words", "matched by words"], ["untracked", "unread"]];

  /** How many interviews have no live record, and the words for where their reading came from. */
  function coverageSources(project) {
    var c = (project && project.sources) || {};
    var present = UNREAD.filter(function (k) { return num(c[k[0]]); });
    return {
      unread: present.reduce(function (sum, k) { return sum + num(c[k[0]]); }, 0),
      breakdown: present.map(function (k) { return c[k[0]] + " " + k[1]; }).join(", ")
    };
  }

  function sessionCoverage(s) {
    if (!s) { return "No interview selected."; }
    if (!s.reportable) { return "This interview ran without a survey."; }
    if (s.source === "untracked") {
      return "No live coverage record for this interview, and no question matched by words: check it by hand.";
    }
    var counted = s.asked.length + " of " + s.total + " survey questions ";
    if (READ_AS[s.source]) { return counted + "found in this interview, " + READ_AS[s.source] + "."; }
    return counted + "asked in this interview.";
  }

  function projectCoverage(p) {
    var from = coverageSources(p);
    var missing = from.unread ? (p.not_found || []) : (p.never_asked || []);
    if (!missing.length) { return "Every survey question has been asked at least once."; }
    var where = " in any of the " + plural(p.sessions_read, "interview", "interviews");
    if (!from.unread) { return missing.length + " never asked" + where + "."; }
    return missing.length + " not found" + where + "; " + from.unread + (from.unread === 1 ? " has" : " have")
      + " no live record (" + from.breakdown + "): check by hand.";
  }

  function coverage(cov) {
    if (!cov) { return "No survey coverage to show."; }
    if (cov.error) { return "Coverage could not be read."; }
    var parts = [sessionCoverage(cov.session)];
    if (cov.project) { parts.push(projectCoverage(cov.project)); }
    return parts.join(" ");
  }

  function numbers(summary, session) {
    if (!summary) {
      return session ? "The fact corpus could not be read, so there is nothing to count."
        : "No interview selected, so there is nothing to count.";
    }
    if (!summary.fact_count) { return "No claims from this interview are in the corpus."; }
    var touched = num(summary.hypotheses_touched);
    var split = [summary.evidence_facts + " evidence", summary.inference_facts + " inference"];
    var rest = summary.fact_count - num(summary.evidence_facts) - num(summary.inference_facts);
    if (rest) { split.push(rest + " of neither kind"); }
    return plural(summary.fact_count, "claim", "claims") + " from this interview, bearing on "
      + (touched ? plural(touched, "hypothesis", "hypotheses") : "no hypothesis") + ": " + split.join(", ") + ".";
  }

  function talk(meter) {
    if (!meter || !meter.measurable) { return "No transcript to count, so nothing to measure."; }
    var mine = (meter.speakers || {})[meter.interviewer_key];
    if (!mine) { return "You do not appear in this transcript; " + meter.total_words + " words were counted."; }
    return "You spoke " + Math.round(mine.share * 100) + "% of the " + meter.total_words + " words.";
  }

  function transcript(turns) {
    var list = turns || [];
    if (!list.length) { return "No transcript for this interview."; }
    var mine = list.filter(function (t) { return t.speaker === "you"; }).length;
    var theirs = list.filter(function (t) { return t.speaker === "them"; }).length;
    var rest = list.length - mine - theirs;
    return plural(list.length, "turn", "turns") + ": " + mine + " yours, " + theirs + " theirs"
      + (rest ? ", " + rest + " unlabelled" : "") + ".";
  }

  var EXTRACTION_TEXT = {
    "not-extracted": "Not extracted yet, so nothing on this page reflects this interview.",
    "no-facts-from-this-interview": "No claims from this interview are in the corpus.",
    "no-hypotheses": "No hypotheses yet, so no claim can bear on one.",
    "unreadable": "The fact corpus could not be read."
  };

  /** The line for the interview as a whole: the extraction banner's counts and what moved. */
  function interview(extraction, list, session) {
    if (!session) { return "No interview selected."; }
    if (!extraction) { return "The extraction status is not one this page knows."; }
    if (extraction.status !== "extracted") {
      return EXTRACTION_TEXT[extraction.status] || "The extraction status is not one this page knows.";
    }
    var moved = (list || []).filter(function (s) { return s.moved_this_interview; }).length;
    return plural(extraction.facts_this_interview, "claim", "claims") + " extracted, "
      + extraction.facts_without_bearings + " bearing on no hypothesis; "
      + (moved ? plural(moved, "hypothesis", "hypotheses") : "no hypothesis") + " moved.";
  }

  function walkedClause(data) {
    return num(data.offers_total) ? "You walked past " + num(data.walked_past_total) + " of " + data.offers_total + " offers."
      : "No offer to follow up was detected.";
  }

  function mirror(data) {
    if (!data || data.error) { return "The mirror could not be loaded."; }
    var interviews = data.interviews || [];
    if (!interviews.length) { return "No interviews with speech in this project yet."; }
    var critiqued = interviews.filter(function (i) { return i.critiqued; }).length;
    var habit;
    if (critiqued < 2) {
      habit = "A habit needs two critiqued interviews; " + critiqued + " of " + interviews.length
        + (critiqued === 1 ? " is" : " are") + " critiqued.";
    } else if (!(data.habits || []).length) {
      habit = "No question habit recurs across interviews.";
    } else {
      var h = data.habits[0];
      habit = "Your most frequent habit: " + (MIRROR_FLAGS[h.flag] || h.flag) + ", in " + h.interviews + " of "
        + critiqued + " interviews, " + plural(h.questions, "question", "questions") + ".";
    }
    return habit + " " + walkedClause(data);
  }

  /** Every opportunity in tree order (pre-order), and every solution under them. */
  function treeNodes(tree) {
    var opportunities = [], solutions = [];
    (function visit(nodes) {
      (nodes || []).forEach(function (n) {
        opportunities.push(n);
        visit(n.children);
        (n.solutions || []).forEach(function (s) { solutions.push(s); });
      });
    }(tree));
    return { opportunities: opportunities, solutions: solutions };
  }

  /** The most interviews; the first in tree order on a tie. */
  function strongest(opportunities) {
    var best = null;
    opportunities.forEach(function (n) { if (!best || num(n.interviews) > num(best.interviews)) { best = n; } });
    return best;
  }

  function isTree(data) { return data && data.status === "fresh" && Array.isArray(data.tree); }

  var SYNTHESIS_TEXT = {
    absent: "No synthesis yet. The section shows the command that makes one.",
    stale: "The cached synthesis is out of date.",
    unreadable: "The cached synthesis cannot be used.",
    "no-claims": "No extracted claims yet, so there is nothing to synthesize.",
    "corpus-unreadable": "The claims could not be read."
  };

  function outcomeClause(outcome) {
    var o = outcome || {};
    if (!String(o.text || "").trim()) { return "No outcome set."; }
    return (o.proposed ? "Outcome (proposed by the model): " : "Outcome: ") + String(o.text).trim().replace(/[.\s]+$/, "") + ".";
  }

  var OUT_OF_DATE = " Ask your agent to rebuild it.";

  /** What this interview did to the tree, as a clause; "" when the marks cannot be read. */
  function marksClause(data, sessionId) {
    var M = window.SynthesisMarks;
    if (!M || M.state(data, sessionId) !== "marked") { return ""; }
    var sum = M.summary(data.tree, sessionId);
    var parts = [];
    if (sum.stronger) { parts.push(M.SYMBOL.stronger + sum.stronger + " stronger"); }
    if (sum.weaker) { parts.push(M.SYMBOL.weaker + sum.weaker + " weaker"); }
    if (sum.mixed) { parts.push(M.SYMBOL.mixed + sum.mixed + " mixed"); }
    if (sum.added) { parts.push(sum.added + " new"); }
    return parts.length ? " This interview: " + parts.join(", ") + "." : " This interview touched no node.";
  }

  function synthesis(data, sessionId) {
    if (!data) { return "The synthesis could not be loaded."; }
    if (data.status === "stale") { return SYNTHESIS_TEXT.stale + OUT_OF_DATE; }
    if (!isTree(data)) { return SYNTHESIS_TEXT[data.status] || "No synthesis to show."; }
    var lead = outcomeClause(data.outcome);
    var nodes = treeNodes(data.tree);
    var marks = marksClause(data, sessionId);
    if (!nodes.opportunities.length) { return lead + " No opportunity survived the checks." + marks; }
    var established = nodes.opportunities.filter(function (n) { return n.status === "established"; }).length;
    var top = strongest(nodes.opportunities);
    var shape = plural(nodes.opportunities.length, "opportunity", "opportunities") + ", " + data.tree.length
      + " at the top level, " + established + " established; strongest: “" + shortStatement(top.statement) + "”, heard in "
      + num(top.interviews) + " of " + num(data.total_interviews) + ".";
    var n = nodes.solutions.length;
    var leaning = nodes.solutions.filter(function (s) { return s.signal === "leaning for"; }).length;
    var tail = !n ? "No solutions yet." : plural(n, "solution", "solutions") + ", "
      + (leaning ? leaning + " leaning for." : "none leaning for yet.");
    return lead + " " + shape + " " + tail + marks;
  }

  /** The tiny counts on the nav, keyed by section. `null` clears a count. */
  function counts(kind, data) {
    if (kind === "review") {
      return { standings: (data.standings || []).length, transcript: (data.transcript || []).length };
    }
    if (kind === "proposals") {
      var n = ((data && data.proposals) || []).length;
      return { proposals: n || null };
    }
    if (kind === "synthesis") {
      return { synthesis: isTree(data) ? treeNodes(data.tree).opportunities.length : null };
    }
    return {};
  }

  window.HubLines = {
    MIRROR_FLAGS: MIRROR_FLAGS, shortStatement: shortStatement, treeNodes: treeNodes,
    standings: standings, proposals: proposals, addHypothesis: addHypothesis, coverage: coverage,
    coverageSources: coverageSources,
    numbers: numbers, talk: talk, transcript: transcript, interview: interview, mirror: mirror,
    synthesis: synthesis, counts: counts
  };
}());
