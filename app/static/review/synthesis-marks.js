// What one interview did to each node of the opportunity tree, as
// `window.SynthesisMarks`. Pure: no DOM, no load-time side effects beyond
// defining the global. Every mark is counted by code from the claims a node
// cites; the bearing -> direction table below is the only copy in the hub.
(function () {
  "use strict";

  var DIRECTION = {
    experiences: "for", not_experienced: "against", already_met: "against",
    supports: "for", contradicts: "against"
  };
  var SYMBOL = { stronger: "\u25B2", weaker: "\u25BC", mixed: "\u25C6" };
  var NEW_LABEL = "new";

  function groups(node) {
    return (node && node.claims_by_interview) || [];
  }

  /** "3 claims, 1 for, 2 against". */
  function detail(forCount, againstCount) {
    var total = forCount + againstCount;
    var parts = [total + (total === 1 ? " claim" : " claims")];
    if (forCount) { parts.push(forCount + " for"); }
    if (againstCount) { parts.push(againstCount + " against"); }
    return parts.join(", ");
  }

  function forNode(node, sessionId) {
    if (!sessionId) { return null; }
    var forCount = 0;
    var againstCount = 0;
    groups(node).forEach(function (group) {
      if (group.session_id !== sessionId) { return; }
      (group.facts || []).forEach(function (fact) {
        var dir = Object.prototype.hasOwnProperty.call(DIRECTION, fact.bearing) ? DIRECTION[fact.bearing] : null;
        if (dir === "for") { forCount += 1; } else if (dir === "against") { againstCount += 1; }
      });
    });
    if (!forCount && !againstCount) { return null; }
    return {
      direction: forCount && againstCount ? "mixed" : (forCount ? "stronger" : "weaker"),
      isNew: groups(node).every(function (group) { return group.session_id === sessionId; }),
      forCount: forCount,
      againstCount: againstCount,
      detail: detail(forCount, againstCount),
      title: detail(forCount, againstCount).replace(", ", " from this interview: ")
    };
  }

  function state(data, sessionId) {
    if (!data || data.status !== "fresh") { return "stale"; }
    if (!sessionId) { return "no-session"; }
    if ((data.built_from || []).indexOf(sessionId) === -1) { return "no-claims"; }
    return "marked";
  }

  function visit(nodes, fn) {
    (nodes || []).forEach(function (node) {
      fn(node);
      visit(node.solutions, fn);
      visit(node.children, fn);
    });
  }

  function summary(tree, sessionId) {
    var out = { stronger: 0, weaker: 0, mixed: 0, added: 0, touched: 0 };
    if (!sessionId) { return out; }
    visit(tree, function (node) {
      var mark = forNode(node, sessionId);
      if (!mark) { return; }
      out[mark.direction] += 1;
      out.touched += 1;
      if (mark.isNew) { out.added += 1; }
    });
    return out;
  }

  var WORD = { stronger: "Stronger", weaker: "Weaker", mixed: "Mixed" };

  /** node -> mark | null for one interview; always null unless the tree is marked for it. */
  function lookup(data, sessionId) {
    if (state(data, sessionId) !== "marked") { return function () { return null; }; }
    return function (node) { return forNode(node, sessionId); };
  }

  /** The line under a detail panel's title: "▲ Stronger from this interview: <title>". */
  function line(mark) {
    return SYMBOL[mark.direction] + " " + WORD[mark.direction] + " from this interview: " + mark.detail;
  }

  /** The spans that lead a card or an outline row: the symbol, then "new" when it is. */
  function nodes(mark) {
    var el = window.SynthesisUI.el;
    var out = [];
    var sym = el("span", "ost-mark ost-mark-" + mark.direction, SYMBOL[mark.direction]);
    sym.setAttribute("title", mark.title);
    out.push(sym);
    if (mark.isNew) { out.push(el("span", "ost-mark-new", NEW_LABEL)); }
    return out;
  }

  window.SynthesisMarks = {
    DIRECTION: DIRECTION, SYMBOL: SYMBOL, NEW_LABEL: NEW_LABEL,
    forNode: forNode, state: state, summary: summary, lookup: lookup, line: line, nodes: nodes
  };
})();
