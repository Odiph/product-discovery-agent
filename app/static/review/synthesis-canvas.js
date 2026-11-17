// The tree view: the opportunity solution tree drawn top-down, as Torres
// draws it, so siblings on a level can be compared side by side. Cards are
// HTML buttons placed by synthesis-layout.js; the connectors are one SVG
// behind them, built with createElementNS and setAttribute only. The canvas
// scrolls inside its own container, never the page, and zooms (out, in, fit
// to width). Clicking a card opens its details in the panel below the tree.
// Loaded after synthesis-layout.js and synthesis-pan.js. textContent only.
(function () {
  "use strict";

  var ui = window.SynthesisUI;
  var L = window.SynthesisLayout;
  var el = ui.el, said = ui.said, plural = ui.plural;
  var PAN = 80, STEP = 1.25;
  var MINUS = "−";

  function px(n) { return Math.round(n) + "px"; }

  function place(node, card) {
    node.style.setProperty("left", px(card.x));
    node.style.setProperty("top", px(card.y));
    node.style.setProperty("width", px(card.w));
    node.style.setProperty("height", px(card.h));
  }

  function warnDot(warnings) {
    if (!(warnings || []).length) { return null; }
    var dot = el("span", "ost-dot");
    dot.setAttribute("title", warnings.map(function (w) { return w.message; }).join("; "));
    dot.appendChild(el("span", "ost-sr", plural(warnings.length, "warning", "warnings")));
    return dot;
  }

  function opportunityFace(n, total) {
    var heard = "heard in " + (n.interviews || 0) + " of " + plural(total, "interview", "interviews");
    var foot = el("span", "ost-card-foot");
    foot.appendChild(el("span", "ost-status " + (ui.STATUS_CLASS[n.status] || ""), n.status));
    var count = el("span", "ost-card-n", (n.interviews || 0) + "/" + total);
    count.setAttribute("title", heard);
    foot.appendChild(count);
    var label = n.statement + ". " + n.status + ", " + heard;
    return { foot: foot, label: label };
  }

  function solutionFace(s) {
    var foot = el("span", "ost-card-foot");
    foot.appendChild(el("span", "ost-signal signal-" + String(s.signal || "").replace(/\s+/g, "-"), s.signal));
    var n = (s.assumptions || []).length;
    foot.appendChild(el("span", "ost-card-n", plural(n, "assumption", "assumptions")));
    var label = "Solution: " + s.statement + ". Interview signal " + s.signal + ", " + plural(n, "assumption", "assumptions");
    return { foot: foot, label: label };
  }

  function face(card, total, mark) {
    var n = card.node;
    var button = el("button", "ost-card ost-card-" + card.kind);
    button.setAttribute("type", "button");
    button.setAttribute("aria-pressed", "false");
    if (card.kind === "outcome") {
      button.appendChild(el("span", "ost-card-label", n.proposed ? "Outcome, proposed by the model" : "Outcome"));
      button.appendChild(said("span", "ost-card-text", String(n.text || "").trim() || "No outcome set yet."));
      return button;
    }
    var made = card.kind === "solution" ? solutionFace(n) : opportunityFace(n, total);
    if (mark) { window.SynthesisMarks.nodes(mark).forEach(function (m) { button.appendChild(m); }); }
    button.appendChild(said("span", "ost-card-text", n.statement));
    var dot = warnDot(n.warnings);
    if (dot) { made.foot.appendChild(dot); made.label += ", " + plural(n.warnings.length, "warning", "warnings"); }
    button.appendChild(made.foot);
    button.setAttribute("aria-label", mark ? made.label + ", " + mark.title : made.label);
    return button;
  }

  function fold(card, open, onToggle) {
    var n = card.node;
    var count = (n.children || []).length + (n.solutions || []).length;
    if (card.kind !== "opportunity" || !count) { return null; }
    var button = el("button", "ost-fold", open ? MINUS : "+" + count);
    button.setAttribute("type", "button");
    button.setAttribute("aria-expanded", open ? "true" : "false");
    button.setAttribute("aria-label", ui.underWords((n.children || []).length, (n.solutions || []).length) + " under: "
      + n.statement);
    button.setAttribute("data-fold", n.id);
    button.addEventListener("click", function () { onToggle(n.id); });
    return button;
  }

  // The SVG namespace, taken from the parsed <svg> in index.html.
  function svgNamespace() {
    var probe = document.getElementById("ost-svg");
    return probe && probe.namespaceURI ? probe.namespaceURI : null;
  }

  function links(layout) {
    var SVG = svgNamespace();
    if (!SVG) { return null; }
    var byId = {};
    layout.cards.forEach(function (c) { byId[c.id] = c; });
    var svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "ost-links");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", String(Math.ceil(layout.width)));
    svg.setAttribute("height", String(Math.ceil(layout.height)));
    layout.edges.forEach(function (e) {
      var path = document.createElementNS(SVG, "path");
      path.setAttribute("d", L.connector(byId[e.from], byId[e.to]));
      path.setAttribute("class", "ost-link ost-link-" + byId[e.to].kind);
      path.setAttribute("data-to", e.to);
      svg.appendChild(path);
    });
    return svg;
  }

  // Under a filter, a kept branch opens so its matches can be seen.
  // A branch the reader shut under this filter stays shut.
  function openFor(tree, view, shown) {
    var open = {};
    Object.keys(view.treeOpen).forEach(function (k) { open[k] = view.treeOpen[k]; });
    if (!shown.active) { return open; }
    ui.walk(tree, function (n) {
      if (n.kind !== "solution" && !view.treeShut[n.id]
          && (n.children || []).some(function (c) { return shown.keep[c.id]; })) { open[n.id] = true; }
    });
    return open;
  }

  // Under "only what this interview changed" a solution is a hit only on its own mark.
  function tone(card, wrap, shown, view, marks) {
    if (!shown.active || card.kind === "outcome") { return; }
    var hit = card.kind === "solution" ? shown.match[card.parent] : shown.match[card.id];
    if (card.kind === "solution" && hit && view.filters.changed) { hit = Boolean(marks(card.node)); }
    ui.toggleClass(wrap, hit ? "ost-hit" : "ost-dim", true);
  }

  function detailFor(card, index, total, mark) {
    var box = el("div", "ost-detail-body");
    var n = card.node;
    if (card.kind === "outcome") {
      box.appendChild(said("h3", "ost-detail-title", String(n.text || "").trim() || "No outcome set yet."));
      box.appendChild(el("p", "ost-sub", n.proposed ? "Outcome proposed by the model." : "Your outcome."));
      return box;
    }
    box.appendChild(said("h3", "ost-detail-title", n.statement));
    if (mark) {
      box.appendChild(el("p", "ost-detail-mark ost-detail-mark-" + mark.direction, window.SynthesisMarks.line(mark)));
    }
    if (card.kind === "solution") {
      box.appendChild(el("p", "ost-detail-kind", "Solution, " + (ui.ORIGIN[n.origin] || "origin unknown")
        + ". Interview signal: " + n.signal + "."));
      box.appendChild(ui.signalBar(n));
      if ((n.assumptions || []).length) { box.appendChild(ui.assumptions(n.assumptions)); }
    } else {
      box.appendChild(el("p", "ost-detail-kind", "Opportunity, " + n.status + ": heard in " + (n.interviews || 0)
        + " of " + plural(total, "interview", "interviews") + (n.well_met_for_some ? "; well met for some." : ".")));
      box.appendChild(ui.coverage(index, n.sessions, n.interviews));
    }
    box.appendChild(ui.details(n, index));
    return box;
  }

  function applyZoom(view, parts, layout) {
    var z = view.zoom;
    parts.plane.style.setProperty("transform", "scale(" + z + ")");
    parts.stage.style.setProperty("width", px(layout.width * z));
    parts.stage.style.setProperty("height", px(layout.height * z));
    parts.level.textContent = Math.round(z * 100) + "%";
  }

  function tools(view, parts, layout) {
    var bar = el("div", "ost-canvas-tools");
    bar.setAttribute("role", "group");
    bar.setAttribute("aria-label", "Zoom");
    var api = { node: bar, set: set, onzoom: null };
    // Zooms about `cursor` (viewport px in the scroller) when given, else about the centre.
    function set(z, cursor) {
      var s = parts.scroller, before = view.zoom;
      var at = cursor || { x: s.clientWidth / 2, y: (s.clientHeight || 0) / 2 };
      view.zoom = L.clampZoom(z);
      applyZoom(view, parts, layout);
      var to = L.zoomAround({ left: s.scrollLeft, top: s.scrollTop }, at, before, view.zoom);
      s.scrollLeft = to.left;
      s.scrollTop = to.top;
      if (api.onzoom) { api.onzoom(); }
    }
    [["Zoom out", function () { set(view.zoom / STEP); }], ["Zoom in", function () { set(view.zoom * STEP); }],
      ["Fit to width", function () { set(L.fitScale(layout.width, parts.scroller.clientWidth)); }]]
      .forEach(function (t) {
        var b = el("button", "ost-action", t[0]);
        b.setAttribute("type", "button");
        b.addEventListener("click", t[1]);
        bar.appendChild(b);
      });
    bar.appendChild(parts.level);
    bar.appendChild(el("span", "ost-hint", "Drag to pan · Ctrl+scroll to zoom"));
    return api;
  }

  function keys(scroller, zoom, view) {
    scroller.addEventListener("keydown", function (e) {
      if (e.target !== scroller) { return; }
      var moves = { ArrowLeft: [-PAN, 0], ArrowRight: [PAN, 0], ArrowUp: [0, -PAN], ArrowDown: [0, PAN] };
      if (moves[e.key]) {
        scroller.scrollLeft += moves[e.key][0];
        scroller.scrollTop += moves[e.key][1];
      } else if (e.key === "+" || e.key === "=") {
        zoom.set(view.zoom * STEP);
      } else if (e.key === "-") {
        zoom.set(view.zoom / STEP);
      } else {
        return;
      }
      e.preventDefault();
    });
  }

  /**
   * Draws the tree view into `holder`. `view` keeps treeOpen, zoom and
   * selected across redraws; `redraw()` rebuilds it after a fold.
   */
  function draw(holder, data, index, view, shown, redraw) {
    var total = data.total_interviews || 0;
    var layout = L.layout(data.tree, data.outcome, openFor(data.tree, view, shown));
    var parts = { stage: el("div", "ost-stage"), plane: el("div", "ost-plane"), level: el("span", "ost-zoom-level"),
      scroller: el("div", "ost-scroller") };
    parts.scroller.setAttribute("tabindex", "0");
    parts.scroller.setAttribute("role", "region");
    parts.scroller.setAttribute("aria-label", "The tree. Drag to pan, Ctrl+scroll or pinch to zoom, arrow keys pan, plus and minus zoom.");
    parts.plane.style.setProperty("width", px(layout.width));
    parts.plane.style.setProperty("height", px(layout.height));
    var connectors = links(layout);
    if (connectors) { parts.plane.appendChild(connectors); }
    var detail = el("div", "ost-detail");
    detail.setAttribute("role", "region");
    detail.setAttribute("aria-label", "Selected card");
    var marks = view.marks || function () { return null; };
    var buttons = {}, folds = {}, pan = null;
    function select(card) {
      view.selected = card.id;
      Object.keys(buttons).forEach(function (id) { buttons[id].setAttribute("aria-pressed", id === card.id ? "true" : "false"); });
      detail.textContent = "";
      detail.appendChild(detailFor(card, index, total, marks(card.node)));
    }
    var drawnUnder = {};
    layout.cards.forEach(function (c) { if (c.parent) { drawnUnder[c.parent] = true; } });
    layout.cards.forEach(function (card) {
      var wrap = el("div", "ost-card-wrap ost-wrap-" + card.kind);
      wrap.setAttribute("data-id", card.id);
      place(wrap, card);
      tone(card, wrap, shown, view, marks);
      var button = face(card, total, card.kind === "outcome" ? null : marks(card.node));
      button.addEventListener("click", function () { if (!(pan && pan.suppressClick())) { select(card); } });
      buttons[card.id] = button;
      wrap.appendChild(button);
      var toggle = fold(card, Boolean(drawnUnder[card.id]), function (id) {
        view.treeOpen[id] = !drawnUnder[id];
        view.treeShut[id] = Boolean(drawnUnder[id]);
        view.focusFold = id;
        redraw();
      });
      if (toggle) { folds[card.id] = toggle; wrap.appendChild(toggle); }
      parts.plane.appendChild(wrap);
    });
    parts.stage.appendChild(parts.plane);
    parts.scroller.appendChild(parts.stage);
    var zoom = tools(view, parts, layout);
    keys(parts.scroller, zoom, view);
    pan = window.SynthesisPan.attach(parts.scroller, parts.plane, view, zoom.set, layout);
    zoom.onzoom = pan.refresh;
    var frame = el("div", "ost-frame");
    frame.appendChild(parts.scroller);
    frame.appendChild(pan.minimap);
    holder.appendChild(zoom.node);
    holder.appendChild(frame);
    holder.appendChild(detail);
    // Measured once it is on the page: a detached scroller has no width.
    var first = view.zoom === null;
    if (first) { view.zoom = L.startScale(layout.width, parts.scroller.clientWidth); }
    applyZoom(view, parts, layout);
    // The first view opens on the outcome, which sits in the middle of a wide
    // tree; a redraw (a fold, a filter) keeps the reader where they were.
    if (first) {
      parts.scroller.scrollLeft = Math.max(0, (layout.width * view.zoom + 2 * L.MARGIN - parts.scroller.clientWidth) / 2);
    } else {
      parts.scroller.scrollLeft = view.scrollLeft || 0;
      parts.scroller.scrollTop = view.scrollTop || 0;
    }
    parts.scroller.addEventListener("scroll", function () {
      view.scrollLeft = parts.scroller.scrollLeft;
      view.scrollTop = parts.scroller.scrollTop;
    });
    view.scrollLeft = parts.scroller.scrollLeft;
    view.scrollTop = parts.scroller.scrollTop;
    pan.refresh();
    var chosen = layout.cards.filter(function (c) { return c.id === view.selected; })[0];
    if (chosen) {
      select(chosen);
    } else {
      view.selected = null;
      detail.appendChild(el("p", "ost-sub", "Select a card to see its details here."));
    }
    // A fold redraws the tree; give focus back to the toggle the reader pressed.
    if (view.focusFold && folds[view.focusFold] && folds[view.focusFold].focus) { folds[view.focusFold].focus(); }
    view.focusFold = null;
    return { layout: layout, scroller: parts.scroller };
  }

  window.SynthesisCanvas = { draw: draw };
}());
