// Everything around the tree: the outcome at its root, the solution tally,
// and the notes beside it (the tree-level notes, the hypotheses the tree does
// not place, opinions, the threshold note, the diff and the drops). Loaded
// after synthesis-filter.js. textContent only.
(function () {
  "use strict";

  var ui = window.SynthesisUI;
  var el = ui.el, said = ui.said, plural = ui.plural;

  var SIGNALS = ["leaning for", "mixed", "leaning against", "thin", "no signal"];
  var OPINION_NOTE = "Opinions, not behaviour: weigh lightly (Mom Test).";

  function outcome(o, project) {
    var box = el("div", "ost-outcome");
    var head = el("p", "ost-outcome-label", "Outcome");
    if (o && o.proposed) { head.appendChild(el("span", "ost-proposed", "proposed by the model")); }
    box.appendChild(head);
    var text = String((o && o.text) || "").trim();
    box.appendChild(text ? said("p", "ost-outcome-text", text) : el("p", "ost-outcome-none", "No outcome set yet."));
    if (o && o.proposed) {
      var how = el("p", "ost-sub", "Set your own in ");
      how.appendChild(el("code", null, "python -m app author" + (project ? " --project " + project : "")));
      how.appendChild(el("span", null, "; the next synthesis keeps it."));
      box.appendChild(how);
    }
    return box;
  }

  /** "Solutions by interview signal: 9 leaning for, 3 mixed." or null when there are none. */
  function tally(tree) {
    var by = {}, any = false;
    ui.walk(tree, function (n) { if (n.kind === "solution") { by[n.signal] = (by[n.signal] || 0) + 1; any = true; } });
    if (!any) { return null; }
    var known = SIGNALS.filter(function (s) { return by[s]; }).map(function (s) { return by[s] + " " + s; });
    Object.keys(by).forEach(function (s) { if (SIGNALS.indexOf(s) === -1) { known.push(by[s] + " " + s); } });
    return el("p", "ost-tally", "Solutions by interview signal: " + known.join(", ") + ".");
  }

  function side(cls, title, sub) {
    var box = el("section", "ost-side " + cls);
    box.appendChild(el("h3", null, title));
    if (sub) { box.appendChild(el("p", "ost-side-sub", sub)); }
    return box;
  }

  function treeNotes(warnings) {
    if (!(warnings || []).length) { return null; }
    var box = side("ost-tree-notes", "About the whole tree");
    var list = el("ul", "ost-warnings");
    warnings.forEach(function (w) { list.appendChild(el("li", "ost-warning", w.message)); });
    box.appendChild(list);
    return box;
  }

  function standing(h) {
    var key = el("p", "standing-key ost-standing");
    key.appendChild(el("span", "k for", (h.supporting_interviews || 0) + " for"));
    key.appendChild(el("span", "k against", (h.contrary_interviews || 0) + " against"));
    key.appendChild(el("span", "k unclear", (h.unclear_interviews || 0) + " unclear"));
    key.appendChild(el("span", "ost-total", "in " + plural(h.total_interviews || 0, "interview", "interviews")));
    return key;
  }

  function unplaced(list) {
    if (!(list || []).length) { return null; }
    var box = side("ost-unplaced", "Your hypotheses the tree does not place", "Not a need or a solution, or not matched.");
    var ul = el("ul", "ost-unplaced-list");
    list.forEach(function (h) {
      var li = el("li", "ost-unplaced-item");
      var head = el("p", "ost-unplaced-head");
      head.appendChild(el("span", "ost-hyp", h.hypothesis_id));
      head.appendChild(said("span", "ost-unplaced-text", h.statement));
      li.appendChild(head);
      li.appendChild(standing(h));
      ul.appendChild(li);
    });
    box.appendChild(ul);
    return box;
  }

  function opinions(list, index, open) {
    if (!(list || []).length) { return null; }
    var box = el("section", "ost-side ost-opinions");
    var sessions = {};
    list.forEach(function (o) { sessions[o.session_id] = true; });
    var words = "Heard, not evidence: " + plural(list.length, "opinion", "opinions") + " from "
      + plural(Object.keys(sessions).length, "interview", "interviews");
    var toggle = el("button", "synth-toggle");
    var body = el("div", "ost-opinion-list");
    body.appendChild(el("p", "ost-opinion-note", OPINION_NOTE + " Praise and opinions are never nodes of the tree."));
    var ul = el("ul", "ost-claim-list");
    list.forEach(function (o) {
      var li = el("li");
      li.appendChild(ui.sid(index, o.session_id));
      li.appendChild(said("span", "synth-claim", o.claim));
      ul.appendChild(li);
    });
    body.appendChild(ul);
    box.appendChild(toggle);
    box.appendChild(body);
    ui.disclosure(toggle, body, open, "opinions", function () { return words; });
    return box;
  }

  var DIFF = [["added", "Added"], ["removed", "Removed"], ["moved", "Moved"], ["renamed", "Renamed"]];

  function diffLine(part, e) {
    var text = DIFF.filter(function (d) { return d[0] === part; })[0][1] + " " + e.kind + ": " + e.statement;
    if (part === "moved") { text += ", from " + e.before + " to " + e.after; }
    if (part === "renamed") { text += ", was " + e.before; }
    return said("li", "ost-diff-item", text);
  }

  function diff(d) {
    if (!d) { return null; }
    var box = side("ost-diff", "Since the previous tree");
    var any = DIFF.some(function (p) { return (d[p[0]] || []).length; });
    if (!any) {
      box.textContent = "";
      ui.toggleClass(box, "ost-diff-none", true);
      box.appendChild(el("p", "ost-side-sub", "No change to the tree's structure since the previous synthesis."));
      return box;
    }
    var ul = el("ul", "ost-diff-list");
    DIFF.forEach(function (p) { (d[p[0]] || []).forEach(function (e) { ul.appendChild(diffLine(p[0], e)); }); });
    box.appendChild(ul);
    return box;
  }

  function drops(d) {
    var lines = (d && d.lines) || [];
    if (!lines.length) { return null; }
    return el("p", "note ost-drops", "The checks dropped from the model's answer: " + lines.join("; ") + ".");
  }

  /** The notes beside the tree, in reading order; nulls are left out. */
  function aside(data, index, open) {
    var box = el("aside", "ost-aside");
    box.setAttribute("aria-label", "Beside the tree");
    [treeNotes(data.warnings), unplaced(data.unplaced_hypotheses), opinions(data.opinions, index, open),
      diff(data.diff), drops(data.drops)].forEach(function (n) { if (n) { box.appendChild(n); } });
    if (data.threshold_note) { box.appendChild(el("p", "note ost-threshold", data.threshold_note)); }
    return box;
  }

  window.SynthesisExtras = { outcome: outcome, tally: tally, aside: aside };
}());
