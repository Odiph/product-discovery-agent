// The synthesis panel's building blocks, shared by the tree's other scripts
// (synthesis-node.js, -filter.js, -extras.js, synthesis.js) through
// `window.SynthesisUI`. Loaded first. textContent only: every string here can
// be model or claim text, so nothing is ever parsed as markup, and every node
// that can hold such text is `dir="auto"` so a Hebrew claim beside an English
// one reads in its own direction.
(function () {
  "use strict";

  var nextId = 0;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  // An element holding text that came from the model or from a claim.
  function said(tag, className, text) {
    var node = el(tag, className, text);
    node.setAttribute("dir", "auto");
    return node;
  }

  function toggleClass(node, name, on) {
    var classes = node.className.split(/\s+/).filter(function (c) { return c && c !== name; });
    if (on) { classes.push(name); }
    node.className = classes.join(" ");
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function uid(prefix) { nextId += 1; return prefix + nextId; }

  // `20260615T000000` before `20260615T000000-2` before `20260615T000000-10`.
  function naturalCompare(a, b) {
    var ax = a.split(/(\d+)/), bx = b.split(/(\d+)/);
    for (var i = 0; i < Math.min(ax.length, bx.length); i += 1) {
      if (ax[i] === bx[i]) { continue; }
      var an = /^\d+$/.test(ax[i]), bn = /^\d+$/.test(bx[i]);
      if (an && bn) { return Number(ax[i]) - Number(bx[i]); }
      return ax[i] < bx[i] ? -1 : 1;
    }
    return ax.length - bx.length;
  }

  // Every opportunity and solution in tree order, each with its depth and its
  // parent opportunity (null at the top level).
  function walk(tree, visit) {
    (function down(nodes, depth, parent) {
      (nodes || []).forEach(function (n) {
        visit(n, depth, parent);
        down(n.children, depth + 1, n);
        (n.solutions || []).forEach(function (s) { visit(s, depth + 1, n); });
      });
    }(tree, 0, null));
  }

  // Every interview the payload names, in project order, numbered from 1.
  // Session ids are long timestamps; the panel shows `#3` and keeps the full
  // id in a title, so it is one hover away and never lost.
  function sessionIndex(data) {
    var seen = {};
    function add(list) { (list || []).forEach(function (s) { seen[s] = true; }); }
    walk(data.tree, function (n) {
      add(n.sessions);
      add((n.claims_by_interview || []).map(function (g) { return g.session_id; }));
    });
    add((data.opinions || []).map(function (o) { return o.session_id; }));
    var order = Object.keys(seen).sort(naturalCompare);
    var number = {};
    order.forEach(function (s, i) { number[s] = i + 1; });
    return { order: order, number: number, total: Math.max(data.total_interviews || 0, order.length) };
  }

  function shortId(index, sessionId) {
    return index.number[sessionId] ? "#" + index.number[sessionId] : "#?";
  }

  function sid(index, sessionId) {
    var node = el("span", "synth-sid", shortId(index, sessionId));
    node.setAttribute("title", sessionId);
    return node;
  }

  // One cell per interview, in project order, so the same column is the same
  // interview on every row: scanning down a column follows one interviewee.
  function coverage(index, sessions, count) {
    var inside = {};
    (sessions || []).forEach(function (s) { inside[s] = true; });
    var box = el("span", "synth-coverage");
    var cells = el("span", "synth-cells");
    var named = [];
    index.order.forEach(function (s) {
      var cell = el("span", inside[s] ? "synth-cell on" : "synth-cell");
      cell.setAttribute("title", shortId(index, s) + " " + s + (inside[s] ? "" : ", not here"));
      if (inside[s]) { named.push(shortId(index, s)); }
      cells.appendChild(cell);
    });
    // Interviews with claims that no node or opinion cites: counted in the
    // total, so drawn, but they have no id to place them by.
    for (var i = index.order.length; i < index.total; i += 1) {
      var blank = el("span", "synth-cell");
      blank.setAttribute("title", "an interview nothing here cites");
      cells.appendChild(blank);
    }
    cells.setAttribute("role", "img");
    cells.setAttribute("aria-label", "In " + count + " of " + index.total + " interviews: " + named.join(", "));
    box.appendChild(cells);
    box.appendChild(el("span", "synth-count", count + " of " + index.total + " interviews"));
    return box;
  }

  function copyButton(getText, label) {
    var wrap = el("span", "synth-copy");
    var button = el("button", "synth-copy-button", label || "Copy");
    button.setAttribute("type", "button");
    var status = el("span", "synth-copied");
    status.setAttribute("role", "status");
    button.addEventListener("click", function () {
      var done = function () { status.textContent = "Copied"; };
      var failed = function () { status.textContent = "Could not copy: select the text and copy it by hand."; };
      try {
        navigator.clipboard.writeText(getText()).then(done, failed);
      } catch (e) {
        failed();
      }
    });
    wrap.appendChild(button);
    wrap.appendChild(status);
    return wrap;
  }

  // A button that shows and hides `target`, remembering its state in
  // `open[key]` so a redraw does not close what the reader opened. `label`
  // gives the button's words for each state, or is omitted to keep its own.
  function disclosure(button, target, open, key, label, owner) {
    target.setAttribute("id", uid("synth-region-"));
    button.setAttribute("type", "button");
    button.setAttribute("aria-controls", target.getAttribute("id"));
    function set(isOpen) {
      open[key] = isOpen;
      target.hidden = !isOpen;
      button.setAttribute("aria-expanded", isOpen ? "true" : "false");
      if (label) { button.textContent = label(isOpen); }
      if (owner) { toggleClass(owner, "open", isOpen); }
    }
    button.addEventListener("click", function () { set(!open[key]); });
    set(Boolean(open[key]));
    return set;
  }

  window.SynthesisUI = {
    el: el, said: said, plural: plural, toggleClass: toggleClass, uid: uid, walk: walk,
    sessionIndex: sessionIndex, shortId: shortId, sid: sid, coverage: coverage, copyButton: copyButton,
    disclosure: disclosure
  };
}());
