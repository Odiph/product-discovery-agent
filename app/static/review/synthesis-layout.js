// Where each card of the opportunity solution tree goes, drawn top-down as
// Torres draws it: the outcome at the top, sibling opportunities side by side
// on the level below, sub-opportunities below them, solutions under their
// opportunity. Pure arithmetic, no DOM: synthesis-canvas.js draws what this
// returns, and the tests check it directly. Loaded after synthesis-dom.js.
//
// A small tidy tree: each subtree is as wide as its leaves need, siblings'
// subtrees sit side by side with a gap, and a parent is centred over its
// first and last child. Because every card lies inside its own subtree's span
// and sibling spans never overlap, no two cards on a level can overlap.
(function () {
  "use strict";

  var SIZE = {
    outcome: { w: 300, h: 88 },
    opportunity: { w: 200, h: 104 },
    solution: { w: 184, h: 88 }
  };
  var GAP_X = 20, GAP_Y = 56, ROW = 104;
  /** The stage's margin inside the scroller on each side (synthesis.css .ost-stage: 0.8rem). */
  var MARGIN = 13;
  var ZOOM_MIN = 0.25, ZOOM_MAX = 2;
  // The first view never starts smaller than this: below it a card cannot be
  // read, so a wide tree opens readable and scrolls, and "Fit to width" is
  // one click away.
  var START_MIN = 0.6;

  function sizeOf(kind) { return SIZE[kind] || SIZE.opportunity; }

  // The nodes drawn under `n`: its child opportunities, then its solutions,
  // only when its branch is open.
  function under(n, open) {
    if (n.kind === "solution" || !open[n.id]) { return []; }
    return (n.children || []).concat(n.solutions || []);
  }

  function measure(n, open) {
    var kids = under(n, open).map(function (k) { return measure(k, open); });
    var span = kids.reduce(function (sum, k) { return sum + k.width; }, 0) + Math.max(0, kids.length - 1) * GAP_X;
    return { node: n, kids: kids, width: Math.max(sizeOf(n.kind).w, span) };
  }

  function place(m, left, depth, out, parent) {
    var size = sizeOf(m.node.kind);
    var span = m.kids.reduce(function (sum, k) { return sum + k.width; }, 0) + Math.max(0, m.kids.length - 1) * GAP_X;
    var x = left + (m.width - span) / 2;
    var centres = m.kids.map(function (k) {
      var c = place(k, x, depth + 1, out, m.node.id);
      x += k.width + GAP_X;
      return c;
    });
    var centre = centres.length ? (centres[0] + centres[centres.length - 1]) / 2 : left + m.width / 2;
    out.cards.push({ id: m.node.id, kind: m.node.kind, depth: depth, x: centre - size.w / 2, y: depth * (ROW + GAP_Y),
      w: size.w, h: size.h, node: m.node, parent: parent });
    out.edges.push({ from: parent, to: m.node.id });
    return centre;
  }

  /**
   * The layout for `tree` (top-level opportunities) under `outcome`, with
   * `open[id]` true for each opportunity whose branch is shown. Returns
   * { cards, edges, width, height }; card x/y are their top-left corners.
   */
  function layout(tree, outcome, open) {
    var out = { cards: [], edges: [] };
    var tops = (tree || []).map(function (n) { return measure(n, open); });
    var span = tops.reduce(function (sum, k) { return sum + k.width; }, 0) + Math.max(0, tops.length - 1) * GAP_X;
    var width = Math.max(SIZE.outcome.w, span);
    var x = (width - span) / 2;
    tops.forEach(function (m) { place(m, x, 1, out, "outcome"); x += m.width + GAP_X; });
    out.cards.push({ id: "outcome", kind: "outcome", depth: 0, x: (width - SIZE.outcome.w) / 2, y: 0,
      w: SIZE.outcome.w, h: SIZE.outcome.h, node: outcome || {}, parent: null });
    // Tab and reading order: the outcome, then each level left to right, as the eye reads it.
    out.cards.sort(function (a, b) { return (a.depth - b.depth) || (a.x - b.x); });
    var deepest = out.cards.reduce(function (d, c) { return Math.max(d, c.depth); }, 0);
    out.width = width;
    out.height = deepest * (ROW + GAP_Y) + ROW;
    return out;
  }

  /** The scale at which a layout `width` wide fits `available` pixels, never above 1. */
  function fitScale(width, available) {
    if (!(width > 0) || !(available > 0)) { return 1; }
    var room = available - 2 * MARGIN;
    if (!(room > 0)) { return ZOOM_MIN; }
    return Math.max(ZOOM_MIN, Math.min(1, room / width));
  }

  /** The zoom a tree opens at: fitted, but never below a readable size. */
  function startScale(width, available) { return Math.max(Math.min(1, START_MIN), fitScale(width, available)); }

  function clampZoom(scale) { return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, scale)); }

  /**
   * The scroll position that keeps the plane point under `cursor` (viewport px
   * inside the scroller) where it is when the zoom changes from `from` to `to`.
   */
  function zoomAround(scroll, cursor, from, to) {
    var k = to / from;
    return {
      left: Math.max(0, (scroll.left + cursor.x - MARGIN) * k + MARGIN - cursor.x),
      top: Math.max(0, (scroll.top + cursor.y - MARGIN) * k + MARGIN - cursor.y)
    };
  }

  /** The bounding box of the card `id` and every drawn card under it, or null when there is no such card. */
  function branchBox(layout, id) {
    var byId = {};
    layout.cards.forEach(function (c) { byId[c.id] = c; });
    if (!byId[id]) { return null; }
    var inside = {};
    inside[id] = true;
    var grew = true;
    while (grew) {
      grew = false;
      layout.cards.forEach(function (c) {
        if (c.parent && inside[c.parent] && !inside[c.id]) { inside[c.id] = true; grew = true; }
      });
    }
    var cards = layout.cards.filter(function (c) { return inside[c.id]; });
    var x = Math.min.apply(null, cards.map(function (c) { return c.x; }));
    var y = Math.min.apply(null, cards.map(function (c) { return c.y; }));
    var right = Math.max.apply(null, cards.map(function (c) { return c.x + c.w; }));
    var bottom = Math.max.apply(null, cards.map(function (c) { return c.y + c.h; }));
    return { x: x, y: y, w: right - x, h: bottom - y };
  }

  /** The zoom that fits `box` inside a `viewW` x `viewH` view, less MARGIN on each side, as fitScale does. */
  function fitBox(box, viewW, viewH) {
    if (!(viewW > 0) || !(viewH > 0) || !(box.w > 0) || !(box.h > 0)) { return 1; }
    var roomW = viewW - 2 * MARGIN, roomH = viewH - 2 * MARGIN;
    if (!(roomW > 0) || !(roomH > 0)) { return ZOOM_MIN; }
    return clampZoom(Math.min(roomW / box.w, roomH / box.h));
  }

  /** A connector from the bottom centre of `a` to the top centre of `b`, as an SVG path. */
  function connector(a, b) {
    var x1 = a.x + a.w / 2, y1 = a.y + a.h, x2 = b.x + b.w / 2, y2 = b.y;
    var mid = (y1 + y2) / 2;
    return "M" + x1 + " " + y1 + " C" + x1 + " " + mid + " " + x2 + " " + mid + " " + x2 + " " + y2;
  }

  window.SynthesisLayout = { layout: layout, fitScale: fitScale, startScale: startScale, clampZoom: clampZoom,
    zoomAround: zoomAround, branchBox: branchBox, fitBox: fitBox,
    connector: connector, START_MIN: START_MIN,
    SIZE: SIZE, GAP_X: GAP_X, MARGIN: MARGIN };
}());
