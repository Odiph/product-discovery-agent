// The tree's filters: status, "has solutions", "has warnings" and a search
// over statements. Client-side and read-only. Loaded after synthesis-node.js.
//
// A node is a MATCH when it passes every filter; it is KEPT when it matches or
// something under it does, so a match never loses the path that leads to it.
// A kept node that does not match is drawn as context. The controls are built
// once and never redrawn, so the search box keeps focus while the tree below
// it changes.
(function () {
  "use strict";

  var ui = window.SynthesisUI;
  var el = ui.el;

  var STATUSES = [["established", "Established"], ["recurring", "Recurring"], ["single story", "Single story"]];

  function fresh() { return { status: "all", solutions: false, warnings: false, changed: false, query: "" }; }

  function isActive(view) {
    return view.status !== "all" || view.solutions || view.warnings || view.changed || Boolean(view.query.trim());
  }

  function warns(n) {
    return (n.warnings || []).length > 0 || (n.solutions || []).some(function (s) { return (s.warnings || []).length > 0; });
  }

  function says(n, query) {
    if (!query) { return true; }
    var hit = function (text) { return String(text || "").toLowerCase().indexOf(query) !== -1; };
    return hit(n.statement) || (n.solutions || []).some(function (s) { return hit(s.statement); });
  }

  // "Changed" keeps an opportunity this interview marked, or one whose solution it marked.
  function touched(n, marksFn) {
    return Boolean(marksFn(n)) || (n.solutions || []).some(function (s) { return Boolean(marksFn(s)); });
  }

  function matches(n, view, query, marksFn) {
    return (view.status === "all" || n.status === view.status)
      && (!view.solutions || (n.solutions || []).length > 0)
      && (!view.warnings || warns(n))
      && (!view.changed || touched(n, marksFn))
      && says(n, query);
  }

  /** The verdict for every opportunity: { active, match, keep, matched, total }. */
  function evaluate(tree, view, marksFn) {
    var marks = marksFn || function () { return null; };
    var query = view.query.trim().toLowerCase();
    var out = { active: isActive(view), match: {}, keep: {}, matched: 0, total: 0 };
    (function down(nodes) {
      var any = false;
      (nodes || []).forEach(function (n) {
        out.total += 1;
        var own = matches(n, view, query, marks);
        var below = down(n.children);
        if (own) { out.match[n.id] = true; out.matched += 1; }
        if (own || below) { out.keep[n.id] = true; any = true; }
      });
      return any;
    }(tree));
    return out;
  }

  function counts(tree) {
    var by = {};
    ui.walk(tree, function (n) { if (n.kind !== "solution") { by[n.status] = (by[n.status] || 0) + 1; } });
    return by;
  }

  function chip(text, count) {
    var b = el("button", "synth-chip", count === undefined ? text : text + " ");
    b.setAttribute("type", "button");
    if (count !== undefined) { b.appendChild(el("span", "ost-chip-n", String(count))); }
    return b;
  }

  function pressed(button, on) { button.setAttribute("aria-pressed", on ? "true" : "false"); }

  function statusRow(tree, view, changed) {
    var row = el("div", "synth-chips ost-filter-status");
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Status");
    var by = counts(tree);
    var options = [["all", "All"]].concat(STATUSES.filter(function (s) { return by[s[0]]; }));
    var buttons = options.map(function (opt) {
      var b = chip(opt[1], opt[0] === "all" ? undefined : by[opt[0]]);
      b.addEventListener("click", function () { view.status = opt[0]; changed(); });
      row.appendChild(b);
      return b;
    });
    return { node: row, sync: function () { buttons.forEach(function (b, i) { pressed(b, options[i][0] === view.status); }); } };
  }

  function toggles(view, changed) {
    var row = el("div", "synth-chips ost-filter-has");
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Show only");
    var defs = [["solutions", "Has solutions"], ["warnings", "Has warnings"]];
    var buttons = defs.map(function (d) {
      var b = chip(d[1]);
      ui.toggleClass(b, "ost-toggle-" + d[0], true);
      b.addEventListener("click", function () { view[d[0]] = !view[d[0]]; changed(); });
      row.appendChild(b);
      return b;
    });
    return { node: row, sync: function () { buttons.forEach(function (b, i) { pressed(b, view[defs[i][0]]); }); } };
  }

  // Shown only while the tree is marked for the interview on screen.
  function changedBox(view, changed, marked) {
    var wrap = el("div", "ost-filter-changed");
    var input = el("input", "ost-changed-input");
    var id = ui.uid("ost-changed-");
    input.setAttribute("id", id);
    input.setAttribute("type", "checkbox");
    input.addEventListener("change", function () { view.changed = Boolean(input.checked); changed(); });
    var label = el("label", null, "Only what this interview changed");
    label.setAttribute("for", id);
    wrap.appendChild(input);
    wrap.appendChild(label);
    return { node: wrap, sync: function () { wrap.hidden = !marked(); input.checked = Boolean(view.changed); } };
  }

  function searchBox(view, changed) {
    var wrap = el("div", "ost-search-wrap");
    var input = el("input", "ost-search");
    var id = ui.uid("ost-search-");
    input.setAttribute("id", id);
    input.setAttribute("type", "search");
    input.setAttribute("placeholder", "Words in a statement");
    input.setAttribute("autocomplete", "off");
    var label = el("label", "ost-search-label", "Search");
    label.setAttribute("for", id);
    input.addEventListener("input", function () { view.query = String(input.value || ""); changed(); });
    wrap.appendChild(label);
    wrap.appendChild(input);
    return { node: wrap, input: input,
      sync: function () { if (input.value !== view.query) { input.value = view.query; } } };
  }

  function action(text, cls, onClick) {
    var b = el("button", "ost-action " + cls, text);
    b.setAttribute("type", "button");
    b.addEventListener("click", onClick);
    return b;
  }

  /**
   * The controls bar. `hooks.changed()` redraws the tree; `hooks.all(open)`
   * opens or closes every branch; `hooks.marked()` says whether the tree is
   * marked for an interview (it gates the "changed" filter). Returns { node, sync }.
   */
  function controls(tree, view, hooks) {
    var bar = el("div", "ost-controls");
    var search = searchBox(view, hooks.changed);
    var marked = hooks.marked || function () { return false; };
    var parts = [statusRow(tree, view, hooks.changed), toggles(view, hooks.changed),
      search, changedBox(view, hooks.changed, marked)];
    parts.forEach(function (p) { bar.appendChild(p.node); });
    var actions = el("div", "ost-actions");
    actions.appendChild(action("Expand all", "ost-expand-all", function () { hooks.all(true); }));
    actions.appendChild(action("Collapse all", "ost-collapse-all", function () { hooks.all(false); }));
    bar.appendChild(actions);
    return { node: bar, sync: function () { parts.forEach(function (p) { p.sync(); }); },
      focus: function () { if (search.input.focus) { search.input.focus(); } } };
  }

  /** The words of the line under the controls, read out when they change. */
  function resultText(shown) {
    return shown.active
      ? "Showing " + shown.matched + " of " + ui.plural(shown.total, "opportunity", "opportunities") + "."
      : "Showing all " + ui.plural(shown.total, "opportunity", "opportunities") + ".";
  }

  window.SynthesisFilter = { fresh: fresh, evaluate: evaluate, controls: controls, resultText: resultText, action: action };
}());
