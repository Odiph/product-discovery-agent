// The synthesis panel: the cached `synthesize` result for the whole project,
// the opportunity solution tree, read from /api/synthesis. Read-only, and this
// page never calls a model: when nothing fresh is cached it says which command
// makes one, with Copy. Every count shown was computed by code from the cited
// claims. Loaded last, after synthesis-dom.js, -node.js, -filter.js,
// -extras.js, -layout.js and -canvas.js. textContent only.
//
// Layout: the outcome, the solution tally, the Tree/Outline switch, the
// controls and the result line, then the tree in either view (top level open,
// deeper branches closed), then the notes beside it. The tree view is drawn
// top-down (synthesis-canvas.js) and is the default on a wide screen; the
// outline (synthesis-node.js) is the default under 700px and the view for a
// screen reader. A filter change redraws the tree only, never the controls,
// so the search box keeps focus.
(function () {
  "use strict";

  var ui = window.SynthesisUI;
  var filter = window.SynthesisFilter;
  var extras = window.SynthesisExtras;
  var el = ui.el, plural = ui.plural;

  var STATE_TEXT = {
    absent: "No synthesis yet.",
    stale: "The cached synthesis is out of date",
    unreadable: "The cached synthesis cannot be used",
    "no-claims": "No extracted claims yet.",
    "corpus-unreadable": "The claims could not be read"
  };
  var STATE_LEAD = {
    "no-claims": "Extract claims from your interviews first:",
    "corpus-unreadable": "Fix that, then run:"
  };
  var WITH_REASON = { stale: true, unreadable: true, "corpus-unreadable": true };

  function publish(data) { if (window.HubNav) { window.HubNav.publish("synthesis", data); } }

  function isTree(data) { return Boolean(data) && data.status === "fresh" && Array.isArray(data.tree); }

  function notFresh(data, host, note) {
    var status = data && data.status;
    var why = STATE_TEXT[status] || "No synthesis to show.";
    if (WITH_REASON[status] && data.reason) { why += ": " + data.reason + "."; } else if (WITH_REASON[status]) { why += "."; }
    note.textContent = why;
    if (!data || !data.how_to || !STATE_TEXT[status]) { return; }
    var state = el("div", "synth-state");
    state.appendChild(el("p", "synth-lead", STATE_LEAD[status] || "Run this to make one (one paid model call):"));
    var line = el("div", "synth-command-line");
    line.appendChild(el("code", "synth-command", data.how_to));
    line.appendChild(ui.copyButton(function () { return data.how_to; }));
    state.appendChild(line);
    if (status === "stale") { state.appendChild(agentCopies(data)); }
    host.appendChild(state);
  }

  // "Copy for your agent" (the slash command) and "Copy as a prompt".
  function agentCopies(data) {
    var row = el("div", "ost-stale-copies");
    if (data.agent_command) { row.appendChild(ui.copyButton(function () { return data.agent_command; }, "Copy for your agent")); }
    if (data.agent_prompt) { row.appendChild(ui.copyButton(function () { return data.agent_prompt; }, "Copy as a prompt")); }
    return row;
  }

  function staleWhy(data) {
    var sessions = data.new_sessions;
    var text = sessions && sessions.length
      ? "The tree was built before " + sessions.length + " newer interview" + (sessions.length === 1 ? "'s" : "s'")
        + " claims. Ask your agent to rebuild it."
      : "The claims, hypotheses or outcome changed since this tree was built. Ask your agent to rebuild it.";
    var dropped = data.last_tree_dropped || 0;
    if (dropped > 0) {
      text += " " + dropped + (dropped === 1 ? " citation in it no longer matches a claim."
        : " citations in it no longer match a claim.");
      var removed = data.last_tree_removed_nodes || 0;
      if (removed > 0) { text += " " + removed + (removed === 1 ? " node left" : " nodes left") + " the tree with them."; }
    }
    return text;
  }

  function staleBanner(data) {
    var banner = el("div", "ost-stale-banner");
    banner.setAttribute("role", "status");
    banner.appendChild(el("p", "synth-lead", staleWhy(data)));
    banner.appendChild(agentCopies(data));
    if (data.how_to) {
      var how = el("div", "ost-stale-how");
      how.hidden = true;
      var line = el("div", "synth-command-line");
      line.appendChild(el("code", "synth-command", data.how_to));
      line.appendChild(ui.copyButton(function () { return data.how_to; }));
      how.appendChild(line);
      var toggle = el("button", "synth-toggle", "Run it yourself");
      ui.disclosure(toggle, how, {}, "how");
      banner.appendChild(toggle);
      banner.appendChild(how);
    }
    return banner;
  }

  // The last tree, drawn like a fresh one but with status "stale" so no marks
  // are computed, under a banner that says why and how to rebuild.
  function staleTree(data, host, note) {
    var shown = Object.assign({}, data.last_tree, { status: "stale", project: data.project, mock_label: data.mock_label });
    host.appendChild(staleBanner(data));
    var grey = el("div", "ost-out-of-date");
    host.appendChild(grey);
    // The note keeps the tree's own summary; the banner says it is out of date and why.
    fresh(shown, grey, note);
  }

  function summary(data) {
    var opportunities = 0, solutions = 0;
    ui.walk(data.tree, function (n) { if (n.kind === "solution") { solutions += 1; } else { opportunities += 1; } });
    return plural(opportunities, "opportunity", "opportunities") + ", " + data.tree.length + " at the top level, and "
      + (solutions ? plural(solutions, "solution", "solutions") : "no solutions") + ", from "
      + plural(data.total_interviews || 0, "interview", "interviews") + ", by " + data.model
      + ". Statuses and counts are computed from the cited claims, in interviews, not by the model.";
  }

  var MODES = [["tree", "Tree"], ["outline", "Outline"]];

  // Tree on a wide screen, the outline on a narrow one; the reader can switch.
  function startMode() {
    var wide = window.matchMedia && window.matchMedia("(min-width: 700px)");
    return wide && wide.matches ? "tree" : "outline";
  }

  function clearButton(view) {
    var none = el("div", "ost-none");
    none.appendChild(el("p", null, "No opportunity matches these filters."));
    none.appendChild(filter.action("Clear filters", "ost-clear", function () {
      Object.assign(view.filters, filter.fresh());
      view.filteredBranch = {};
      view.sync();
      view.redraw();
      view.focusSearch();
    }));
    return none;
  }

  // The tree (either view) under the controls, redrawn on every filter
  // change. The result line lives outside it, so it is one live region that
  // is updated, never replaced.
  function drawTree(holder, data, index, view) {
    if (holder.offsetHeight) { holder.style.setProperty("min-height", holder.offsetHeight + "px"); }
    holder.textContent = "";
    var shown = filter.evaluate(data.tree, view.filters, view.marks);
    view.result.textContent = filter.resultText(shown);
    if (shown.active && !shown.matched) { holder.appendChild(clearButton(view)); }
    if (view.mode === "tree") {
      window.SynthesisCanvas.draw(holder, data, index, view, shown, view.redraw);
    } else if (!shown.active || shown.matched) {
      holder.appendChild(ui.tree(data.tree, { index: index, open: view.open, branch: view.branch,
        filteredBranch: view.filteredBranch, shown: shown, marks: view.marks, changed: view.filters.changed }));
    }
    holder.style.removeProperty("min-height");
  }

  function everyBranch(tree, open) {
    var state = {};
    ui.walk(tree, function (n) { if (n.kind !== "solution") { state[n.id] = open; } });
    return state;
  }

  function modeSwitch(view) {
    var row = el("div", "synth-chips ost-modes");
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "View");
    var buttons = MODES.map(function (m) {
      var b = el("button", "synth-chip", m[1]);
      b.setAttribute("type", "button");
      b.addEventListener("click", function () { view.mode = m[0]; sync(); view.redraw(); });
      row.appendChild(b);
      return b;
    });
    function sync() { buttons.forEach(function (b, i) { b.setAttribute("aria-pressed", MODES[i][0] === view.mode ? "true" : "false"); }); }
    sync();
    return row;
  }

  function newView(tree) {
    var top = {};
    (tree || []).forEach(function (n) { top[n.id] = true; });
    return { filters: filter.fresh(), open: {}, branch: {}, filteredBranch: {}, treeOpen: top, treeShut: {}, zoom: null,
      selected: null, focusFold: null, mode: startMode(), session: null, marks: null };
  }

  // The interview on screen, told by the review section through HubNav. The
  // tree follows it: `follower` is the current tree's setSession, if any.
  var session = null;
  var follower = null;
  if (window.HubNav && window.HubNav.on) {
    window.HubNav.on("review", function (review) {
      session = (review && review.session_id) || null;
      if (follower) { follower(session); }
    });
  }

  // The line above the tree when the chosen interview has no extracted claims.
  function drawNote(box, data, view) {
    box.textContent = "";
    if (window.SynthesisMarks.state(data, view.session) !== "no-claims") { return; }
    box.appendChild(el("p", "synth-lead", "No claims from this interview yet: extract it first."));
    var command = "python -m app extract --project " + data.project + " " + view.session;
    var line = el("div", "synth-command-line");
    line.appendChild(el("code", "synth-command", command));
    line.appendChild(ui.copyButton(function () { return command; }));
    box.appendChild(line);
  }

  function drawMain(data, main, index, view) {
    var count = extras.tally(data.tree);
    if (count) { main.appendChild(count); }
    var holder = el("div", "ost-tree-holder");
    view.result = el("p", "ost-result");
    view.result.setAttribute("role", "status");
    view.redraw = function () { drawTree(holder, data, index, view); };
    var note = el("div", "ost-marks-note");
    var marked = function () { return window.SynthesisMarks.state(data, view.session) === "marked"; };
    function remark() {
      view.marks = window.SynthesisMarks.lookup(data, view.session);
      if (!marked()) { view.filters.changed = false; }
      drawNote(note, data, view);
    }
    remark();
    var bar = filter.controls(data.tree, view.filters, {
      marked: marked,
      changed: function () { view.filteredBranch = {}; view.treeShut = {}; bar.sync(); view.redraw(); },
      all: function (open) {
        view.branch = everyBranch(data.tree, open);
        view.filteredBranch = everyBranch(data.tree, open);
        view.treeOpen = everyBranch(data.tree, open);
        view.treeShut = everyBranch(data.tree, !open);
        view.redraw();
      }
    });
    view.sync = bar.sync;
    // Switching interview re-marks and redraws the tree only: zoom, scroll,
    // folds and the selected card live in `view` and survive.
    view.setSession = function (id) { if (id === view.session) { return; } view.session = id; remark(); bar.sync(); view.redraw(); };
    view.focusSearch = bar.focus;
    main.appendChild(modeSwitch(view));
    main.appendChild(bar.node);
    main.appendChild(view.result);
    main.appendChild(note);
    main.appendChild(holder);
    bar.sync();
  }

  function fresh(data, host, note) {
    var index = ui.sessionIndex(data);
    note.textContent = summary(data);
    host.appendChild(extras.outcome(data.outcome, data.project));
    // The label is written to lead a terminal listing ("...:"); as a tag it stands alone.
    if (data.mock_label) { host.appendChild(el("p", "synth-mock", data.mock_label.replace(/:\s*$/, ""))); }
    var view = newView(data.tree);
    view.session = session;
    var layout = el("div", "ost-layout");
    var main = el("div", "ost-main");
    layout.appendChild(main);
    if (!data.tree.length) {
      main.appendChild(el("p", "ost-empty", "No opportunity survived the checks."));
    } else {
      drawMain(data, main, index, view);
    }
    layout.appendChild(extras.aside(data, index, view.open));
    host.appendChild(layout);
    // Drawn once on the page, so the tree view can measure its width.
    if (view.redraw) { view.redraw(); follower = view.setSession; }
  }

  function render(data) {
    var host = document.getElementById("synthesis");
    var note = document.getElementById("synthesis-note");
    if (!host || !note) { return; }
    host.textContent = "";
    follower = null;
    if (isTree(data)) { fresh(data, host, note); }
    else if (data && data.status === "stale" && data.last_tree && Array.isArray(data.last_tree.tree)) { staleTree(data, host, note); }
    else { notFresh(data, host, note); }
    drawn = signature(data);
    publish(data);
  }

  // What is on screen, as status + the key of the tree drawn.
  var drawn = null;
  function signature(data) {
    var key = data && (data.key || (data.last_tree && data.last_tree.key));
    var news = data && data.new_sessions;
    return [data && data.status, key || "", news ? news.join(",") : "-", data && data.last_tree_dropped,
      data && data.last_tree_removed_nodes].join("|");
  }

  function load() {
    return fetch("/api/synthesis").then(function (r) { return r.json(); });
  }

  load().then(render).catch(function () {
    var note = document.getElementById("synthesis-note");
    if (note) { note.textContent = "The synthesis could not be loaded."; }
    drawn = "failed";
    publish(null);
  });

  // Back on the tab (or the window): the cache may have been rebuilt while
  // away. Redraw only when the status or the tree's key changed, so a reader's
  // zoom and folds are not thrown away for nothing. One fetch at a time.
  var refreshing = false;
  function refresh() {
    if (refreshing || drawn === null || document.visibilityState === "hidden") { return; }
    refreshing = true;
    load().then(function (data) {
        // An error body is a failed refresh, not a cache state: keep what is drawn.
        if (data && data.error && !data.status) { return; }
        if (signature(data) !== drawn) { render(data); }
      })
      .catch(function () { /* keep what is drawn */ })
      .then(function () { refreshing = false; });
  }
  if (document.addEventListener) { document.addEventListener("visibilitychange", refresh); }
  if (window.addEventListener) { window.addEventListener("focus", refresh); }
}());
