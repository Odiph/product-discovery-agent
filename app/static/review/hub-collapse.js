// Long lists on the hub, cut to their first few rows behind "Show all N".
// Hiding only: every row stays in the DOM, so the citations and "show"
// buttons inside them keep working once the list is opened. Remembers
// nothing across reloads. textContent only.
(function () {
  "use strict";

  // A list only collapses when it would hide more than this many rows, so a
  // "Show all 7" never sits under six visible rows.
  var SLACK = 2;

  /**
   * Hides `items` past the first `keep`, except any `pinned` one, and adds a
   * toggle to `into` (inside an <li> when `into` is a list). Returns the
   * toggle, or null when the list is short enough to leave alone.
   */
  function apply(options) {
    var items = options.items || [];
    var keep = options.keep;
    var pinned = options.pinned || function () { return false; };
    var hideable = items.filter(function (node, i) { return i >= keep && !pinned(node); });
    if (hideable.length <= SLACK) { return null; }
    var doc = options.document || document;
    var button = doc.createElement("button");
    button.className = "show-all";
    button.setAttribute("type", "button");
    var open = false;
    function draw() {
      hideable.forEach(function (node) { node.hidden = !open; });
      button.textContent = open ? "Show fewer" : "Show all " + items.length + " " + options.noun;
      button.setAttribute("aria-expanded", open ? "true" : "false");
    }
    button.addEventListener("click", function () { open = !open; draw(); });
    draw();
    var into = options.into;
    if (into.tagName === "UL" || into.tagName === "OL") {
      var row = doc.createElement("li");
      row.className = "show-all-row";
      row.appendChild(button);
      into.appendChild(row);
    } else {
      into.appendChild(button);
    }
    return button;
  }

  /** The element children of `root` whose class list holds `cls`, at any depth. */
  function findByClass(root, cls) {
    var out = [];
    (function walk(node) {
      var kids = node.children || [];
      for (var i = 0; i < kids.length; i += 1) {
        var child = kids[i];
        if ((" " + (child.className || "") + " ").indexOf(" " + cls + " ") !== -1) { out.push(child); }
        walk(child);
      }
    }(root));
    return out;
  }

  /** The direct children of `root` with tag `tag` (upper case). */
  function childrenTagged(root, tag) {
    var out = [];
    var kids = root.children || [];
    for (var i = 0; i < kids.length; i += 1) { if (kids[i].tagName === tag) { out.push(kids[i]); } }
    return out;
  }

  window.HubCollapse = { apply: apply, findByClass: findByClass, childrenTagged: childrenTagged };
}());
