// Moving around the tree: drag the background to pan, Ctrl/Cmd+wheel (which is
// also what a trackpad pinch sends) to zoom at the cursor, an overview
// minimap, and a double-click on an opportunity to fit its branch. The tree
// stays read-only: a pointer-down on a card never starts a pan, and a drag
// that ends over a card does not open it. Loaded after synthesis-layout.js,
// before synthesis-canvas.js. DOM through createElement/setAttribute only.
(function () {
  "use strict";

  var L = window.SynthesisLayout;
  var STEP = 1.25;
  var DRAG = 4;      // px of travel before a press becomes a pan
  var WHEEL_K = 0.01; // zoom per wheel pixel, as an exponent
  var MAP_W = 160;   // minimap width in px
  var MAP_H = 120;   // ... and its tallest, so a deep tree stays a corner overview
  var MAP_MIN_H = 40; // ... and its shortest, so a wide tree's map is still clickable

  function px(n) { return Math.round(n) + "px"; }

  function box(cls) {
    var node = document.createElement("div");
    node.className = cls;
    return node;
  }

  function size(node, w, h) {
    node.style.setProperty("width", px(Math.max(1, w)));
    node.style.setProperty("height", px(Math.max(1, h)));
  }

  function put(node, x, y, w, h) {
    node.style.setProperty("left", px(x));
    node.style.setProperty("top", px(y));
    size(node, w, h);
  }

  // One wheel event's zoom factor: proportional to how far it turned, so a
  // trackpad pinch (many tiny events) is smooth and a mouse notch is at most STEP.
  function factor(e, scroller) {
    var unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? (scroller.clientHeight || 1) : 1;
    var f = Math.exp(-(e.deltaY || 0) * unit * WHEEL_K);
    return Math.max(1 / STEP, Math.min(STEP, f));
  }

  function inCard(target) { return Boolean(target && target.closest && target.closest(".ost-card-wrap")); }

  function drag(scroller) {
    var start = null, moved = false, swallow = false;
    function end() {
      if (start && moved) {
        swallow = true;
        // The click that ends a drag arrives right after pointerup; if it never
        // does (released off a card), do not swallow a later, real click.
        setTimeout(function () { swallow = false; }, 0);
      }
      start = null;
    }
    scroller.addEventListener("pointerdown", function (e) {
      if ((e.button || 0) !== 0 || inCard(e.target)) { return; }
      start = { x: e.clientX, y: e.clientY, left: scroller.scrollLeft, top: scroller.scrollTop };
      moved = false;
      if (scroller.setPointerCapture && e.pointerId !== undefined) { scroller.setPointerCapture(e.pointerId); }
    });
    scroller.addEventListener("pointermove", function (e) {
      if (!start) { return; }
      var dx = e.clientX - start.x, dy = e.clientY - start.y;
      if (!moved && Math.sqrt(dx * dx + dy * dy) < DRAG) { return; }
      moved = true;
      scroller.scrollLeft = start.left - dx;
      scroller.scrollTop = start.top - dy;
    });
    scroller.addEventListener("pointerup", end);
    scroller.addEventListener("pointercancel", end);
    return function suppressClick() {
      var was = swallow;
      swallow = false;
      return was;
    };
  }

  function wheel(scroller, view, zoomSet) {
    scroller.addEventListener("wheel", function (e) {
      if (!(e.ctrlKey || e.metaKey)) { return; }
      e.preventDefault();
      var rect = scroller.getBoundingClientRect();
      zoomSet(view.zoom * factor(e, scroller), { x: e.clientX - rect.left, y: e.clientY - rect.top });
    }, { passive: false });
  }

  function fitBranch(scroller, view, zoomSet, layout) {
    scroller.addEventListener("dblclick", function (e) {
      // Two quick folds are not a request to fit; only the card itself is.
      if (e.target && e.target.closest && e.target.closest(".ost-fold")) { return; }
      var wrap = e.target && e.target.closest ? e.target.closest(".ost-card-wrap") : null;
      if (!wrap || (" " + wrap.className + " ").indexOf(" ost-wrap-opportunity ") < 0) { return; }
      var area = L.branchBox(layout, wrap.getAttribute("data-id"));
      if (!area) { return; }
      zoomSet(L.fitBox(area, scroller.clientWidth, scroller.clientHeight));
      // The stage's margin and the fit's margin are the same MARGIN, so the box's
      // corner at this zoom is exactly where the scroll should sit.
      scroller.scrollLeft = Math.max(0, area.x * view.zoom);
      scroller.scrollTop = Math.max(0, area.y * view.zoom);
    });
  }

  function minimap(scroller, view, layout) {
    var map = box("ost-minimap");
    map.setAttribute("aria-hidden", "true");
    var scale = layout.width > 0 && layout.height > 0 ? Math.min(MAP_W / layout.width, MAP_H / layout.height) : 1;
    size(map, layout.width * scale, Math.max(MAP_MIN_H, layout.height * scale));
    layout.cards.forEach(function (c) {
      var r = box("ost-minimap-card ost-minimap-" + c.kind);
      put(r, c.x * scale, c.y * scale, c.w * scale, c.h * scale);
      map.appendChild(r);
    });
    var port = box("ost-minimap-view");
    map.appendChild(port);
    function refresh() {
      var z = view.zoom || 1;
      put(port, (scroller.scrollLeft - L.MARGIN) / z * scale, (scroller.scrollTop - L.MARGIN) / z * scale,
        scroller.clientWidth / z * scale, scroller.clientHeight / z * scale);
    }
    map.addEventListener("click", function (e) {
      var rect = map.getBoundingClientRect(), z = view.zoom || 1;
      var x = (e.clientX - rect.left) / scale, y = (e.clientY - rect.top) / scale;
      scroller.scrollLeft = Math.max(0, L.MARGIN + x * z - scroller.clientWidth / 2);
      scroller.scrollTop = Math.max(0, L.MARGIN + y * z - scroller.clientHeight / 2);
      refresh();
    });
    scroller.addEventListener("scroll", refresh);
    refresh();
    return { node: map, refresh: refresh };
  }

  /**
   * Wires pan, wheel zoom, branch fit and a minimap onto `scroller`. `zoomSet(z, cursor?)`
   * does the zooming; `layout` is the drawn tree. Returns { minimap, suppressClick, refresh }:
   * the minimap element, a check a card's click handler makes first (true once after a
   * drag), and a redraw of the minimap's viewport for after a zoom.
   */
  function attach(scroller, plane, view, zoomSet, layout) {
    var suppressClick = drag(scroller);
    wheel(scroller, view, zoomSet);
    fitBranch(scroller, view, zoomSet, layout);
    var map = minimap(scroller, view, layout);
    return { minimap: map.node, suppressClick: suppressClick, refresh: map.refresh };
  }

  window.SynthesisPan = { attach: attach, STEP: STEP, DRAG: DRAG };
}());
