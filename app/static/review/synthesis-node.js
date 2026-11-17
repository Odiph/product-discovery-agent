// One node of the opportunity solution tree, as a row in a nested list.
// Loaded after synthesis-dom.js. Every status word and count drawn here was
// computed by code from the cited claims (`synthesis_view`), never by the
// model; the model wrote only the statements, next stories and assumptions.
//
// An opportunity row: branch toggle (when it has anything under it), marker,
// statement (a button: it opens the node's details), then its chips. A
// solution row has a different marker, its signal, bar and origin, and its
// assumptions always visible under it.
(function () {
  "use strict";

  var ui = window.SynthesisUI;
  var el = ui.el, said = ui.said, plural = ui.plural;

  var STATUS_CLASS = { established: "status-established", recurring: "status-recurring", "single story": "status-single" };
  var ORIGIN = { customer: "a customer's idea", operator: "your idea", model: "the model's idea" };
  var BEARING = { not_experienced: "not experienced", already_met: "already met", supports: "for", contradicts: "against" };

  function hypChip(h) {
    var chip = el("span", "ost-hyp", h.hypothesis_id);
    chip.setAttribute("title", h.statement);
    return chip;
  }

  function warnChip(warnings) {
    var chip = el("span", "ost-warn", plural(warnings.length, "warning", "warnings"));
    chip.setAttribute("title", warnings.map(function (w) { return w.message; }).join("; "));
    return chip;
  }

  function story(node) {
    var box = el("div", "ost-story");
    if (!String(node.next_story || "").trim()) {
      box.appendChild(el("p", "ost-story-none", "No next story to ask for yet."));
      return box;
    }
    var top = el("div", "ost-story-top");
    top.appendChild(el("span", "ost-story-label", "Next story to ask for"));
    top.appendChild(ui.copyButton(function () { return node.next_story; }));
    box.appendChild(top);
    box.appendChild(said("p", "ost-story-text", node.next_story));
    return box;
  }

  function claimGroups(node, index) {
    var groups = node.claims_by_interview || [];
    if (!groups.length) { return null; }
    var facts = groups.reduce(function (n, g) { return n + g.facts.length; }, 0);
    var box = el("div", "ost-claims");
    box.appendChild(el("p", "ost-sub", plural(facts, "claim", "claims") + " from "
      + plural(groups.length, "interview", "interviews")));
    var list = el("ul", "ost-claim-groups");
    groups.forEach(function (g) {
      var item = el("li", "ost-claim-group");
      item.appendChild(ui.sid(index, g.session_id));
      var claims = el("ul", "ost-claim-list");
      g.facts.forEach(function (f) {
        var line = el("li");
        line.appendChild(said("span", "synth-claim", f.claim));
        if (BEARING[f.bearing]) { line.appendChild(el("span", "ost-bearing", BEARING[f.bearing])); }
        claims.appendChild(line);
      });
      item.appendChild(claims);
      list.appendChild(item);
    });
    box.appendChild(list);
    return box;
  }

  function more(node, index) {
    var box = el("div", "ost-more");
    box.appendChild(story(node));
    if (node.hypothesis) {
      var maps = el("p", "ost-maps", "Maps your hypothesis " + node.hypothesis.hypothesis_id + ": ");
      maps.appendChild(said("span", null, node.hypothesis.statement));
      box.appendChild(maps);
    }
    if (node.reframed_from) {
      var was = el("p", "ost-reframed", "Reframed from: ");
      was.appendChild(said("span", null, node.reframed_from));
      box.appendChild(was);
    }
    if ((node.warnings || []).length) {
      var list = el("ul", "ost-warnings");
      node.warnings.forEach(function (w) { list.appendChild(el("li", "ost-warning", w.message)); });
      box.appendChild(list);
    }
    var claims = claimGroups(node, index);
    if (claims) { box.appendChild(claims); }
    return box;
  }

  // The row's statement is the button that opens its details.
  function row(node, li, ctx, lead) {
    var line = el("div", "ost-row");
    line.appendChild(lead);
    line.appendChild(el("span", "ost-bullet"));
    var mark = ctx.marks ? ctx.marks(node) : null;
    if (mark) {
      window.SynthesisMarks.nodes(mark).forEach(function (m) { line.appendChild(m); });
      line.appendChild(el("span", "ost-sr", mark.title));
    }
    var statement = said("button", "ost-statement", node.statement);
    line.appendChild(statement);
    var meta = el("span", "ost-meta");
    line.appendChild(meta);
    li.appendChild(line);
    var details = more(node, ctx.index);
    ui.disclosure(statement, details, ctx.open, node.id, null, li);
    return { meta: meta, details: details };
  }

  function bar(s) {
    var f = s.for_interviews || 0, a = s.against_interviews || 0;
    var both = Math.max(0, f + a - (s.touching_interviews || 0));
    var box = el("span", "ost-signal-bar");
    var track = el("span", "standing-track ost-track");
    [["for", f - both], ["unclear", both], ["against", a - both]].forEach(function (pair) {
      if (pair[1] <= 0) { return; }
      var seg = el("span", "standing-seg " + pair[0]);
      seg.style.setProperty("flex-grow", String(pair[1]));
      track.appendChild(seg);
    });
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", "For in " + plural(f, "interview", "interviews") + ", against in " + a
      + (both ? ", " + both + " of them both ways" : ""));
    if (track.children.length) { box.appendChild(track); }
    var key = el("span", "ost-key");
    key.appendChild(el("span", "for", f + " for"));
    key.appendChild(el("span", null, ", "));
    key.appendChild(el("span", "against", a + " against"));
    if (both) {
      key.appendChild(el("span", null, ", "));
      key.appendChild(el("span", "unclear", both + " both ways"));
    }
    box.appendChild(key);
    return box;
  }

  function assumptions(list) {
    var items = (list || []).map(function (a, i) { return { a: a, i: i }; });
    items.sort(function (x, y) { return (Number(Boolean(y.a.leap_of_faith)) - Number(Boolean(x.a.leap_of_faith))) || (x.i - y.i); });
    var ul = el("ul", "ost-assumptions");
    ul.setAttribute("aria-label", "Assumptions");
    items.forEach(function (x) {
      var a = x.a;
      var li = el("li", "ost-assumption" + (a.leap_of_faith ? " leap" : ""));
      if (a.leap_of_faith) { li.appendChild(el("span", "ost-leap", "leap of faith")); }
      [a.type || "untyped", (a.importance || "unrated") + " importance", a.status || "untested"].forEach(function (tag) {
        li.appendChild(el("span", "ost-atag", tag));
      });
      li.appendChild(said("span", "ost-atext", a.text));
      ul.appendChild(li);
    });
    return ul;
  }

  function solution(s, ctx) {
    var li = el("li", "ost-node ost-sol");
    li.setAttribute("data-id", s.id);
    var leaf = el("span", "ost-leaf");
    leaf.setAttribute("aria-hidden", "true");
    if (ctx.changed && !(ctx.marks && ctx.marks(s))) { ui.toggleClass(li, "ost-context", true); }
    var parts = row(s, li, ctx, leaf);
    var signal = el("span", "ost-signal signal-" + String(s.signal || "").replace(/\s+/g, "-"), s.signal);
    parts.meta.appendChild(signal);
    parts.meta.appendChild(bar(s));
    parts.meta.appendChild(el("span", "ost-origin", ORIGIN[s.origin] || "origin unknown"));
    if (s.hypothesis) { parts.meta.appendChild(hypChip(s.hypothesis)); }
    if ((s.warnings || []).length) { parts.meta.appendChild(warnChip(s.warnings)); }
    if ((s.assumptions || []).length) { li.appendChild(assumptions(s.assumptions)); }
    li.appendChild(parts.details);
    return li;
  }

  function opportunityMeta(n, meta, index) {
    meta.appendChild(el("span", "ost-status " + (STATUS_CLASS[n.status] || ""), n.status));
    meta.appendChild(ui.coverage(index, n.sessions, n.interviews));
    if (n.well_met_for_some) { meta.appendChild(el("span", "ost-met", "well met for some")); }
    if (n.hypothesis) { meta.appendChild(hypChip(n.hypothesis)); }
    if ((n.warnings || []).length) { meta.appendChild(warnChip(n.warnings)); }
  }

  function underWords(kids, sols) {
    var parts = [];
    if (kids) { parts.push(plural(kids, "opportunity", "opportunities")); }
    if (sols) { parts.push(plural(sols, "solution", "solutions")); }
    return parts.join(" and ");
  }

  // `ctx.shown`: the filter's verdict (synthesis-filter.js). Children it does
  // not keep are not drawn; a kept node that does not match is context.
  function opportunity(n, depth, ctx) {
    var li = el("li", "ost-node ost-opp depth-" + Math.min(depth, 3));
    li.setAttribute("data-id", n.id);
    var shown = ctx.shown;
    if (shown.active && !shown.match[n.id]) { ui.toggleClass(li, "ost-context", true); }
    var kids = (n.children || []).filter(function (c) { return !shown.active || shown.keep[c.id]; });
    var sols = !shown.active || shown.match[n.id] ? (n.solutions || []) : [];
    var branch = kids.length || sols.length ? el("button", "ost-branch") : el("span", "ost-leaf");
    if (!kids.length && !sols.length) { branch.setAttribute("aria-hidden", "true"); }
    var parts = row(n, li, ctx, branch);
    opportunityMeta(n, parts.meta, ctx.index);
    li.appendChild(parts.details);
    if (!kids.length && !sols.length) { return li; }
    var list = el("ul", "ost-kids");
    kids.forEach(function (c) { list.appendChild(opportunity(c, depth + 1, ctx)); });
    sols.forEach(function (s) { list.appendChild(solution(s, ctx)); });
    li.appendChild(list);
    var words = underWords(kids.length, sols.length);
    // Under a filter every kept branch starts open, in its own map, so the
    // reader's unfiltered choices come back when the filter is cleared.
    var state = shown.active ? ctx.filteredBranch : ctx.branch;
    if (!(n.id in state)) { state[n.id] = shown.active || depth === 0; }
    ui.disclosure(branch, list, state, n.id, null, null);
    branch.setAttribute("aria-label", words + " under this");
    return li;
  }

  function tree(nodes, ctx) {
    var list = el("ul", "ost-tree");
    nodes.forEach(function (n) {
      if (!ctx.shown.active || ctx.shown.keep[n.id]) { list.appendChild(opportunity(n, 0, ctx)); }
    });
    return list;
  }

  window.SynthesisUI.tree = tree;
  window.SynthesisUI.details = more;
  window.SynthesisUI.assumptions = assumptions;
  window.SynthesisUI.signalBar = bar;
  window.SynthesisUI.underWords = underWords;
  window.SynthesisUI.STATUS_CLASS = STATUS_CLASS;
  window.SynthesisUI.ORIGIN = ORIGIN;
  window.SynthesisUI.bearingWords = BEARING;
}());
