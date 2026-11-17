// app/static/author/drafts.js -- the drafted-questions panel of the authoring
// page. Loaded before author.js, and leaves one global, `AuthorDrafts`.
//
// The questions were worded by a model (`python -m app prep --draft --yes`)
// and are read from its cache through `/api/prep`: this page never calls a
// model. Every action changes the survey ON THE PAGE only (Save survey is
// still the one writer), stays visible and is reversible with one Undo.
//
// Bidi: the drafts are often Hebrew. Each free-text string is its own element
// with dir="auto", and none is ever interpolated into an English sentence.
var AuthorDrafts = (function () {
  "use strict";

  var S = AuthorDraftStates;

  // `live` is a persistent role="status" node outside `container`: a node
  // re-created on every render is not announced, so what changed is said there.
  function create(document, container, survey, live) {
    var draft = null;
    var cards = {};
    var expanded = {};
    var batches = {};
    var batchSeq = 0;
    var focusKey = null;
    var toFocus = null;

    function el(tag, className, text) {
      var node = document.createElement(tag);
      if (className) { node.className = className; }
      if (text !== undefined) { node.textContent = text; }
      return node;
    }

    function bidi(tag, className, text) {
      var node = el(tag, className, text);
      node.setAttribute("dir", "auto");
      return node;
    }

    function button(label, className, onClick, key) {
      var b = el("button", className, label);
      b.type = "button";
      b.addEventListener("click", onClick);
      if (key && key === focusKey) { toFocus = b; }
      return b;
    }

    function cardOf(key) { return cards[key] || { status: "fresh" }; }

    function surveyIndex(itemId) {
      var items = survey.items();
      for (var i = 0; i < items.length; i += 1) {
        if (items[i].id === itemId) { return i; }
      }
      return -1;
    }

    // A question the survey already holds, except as the item this card added.
    function alreadyAsked(question, key) {
      var mine = cardOf(key).itemId;
      var wanted = (question.text || "").trim();
      return survey.items().some(function (item) {
        return item.id !== mine && (item.text || "").trim() === wanted;
      });
    }

    function offered() {
      return (draft.questions || []).map(function (q, i) { return { key: "c" + i, q: q }; })
        .filter(function (entry) { return !alreadyAsked(entry.q, entry.key); });
    }

    // An added question removed from the survey by hand: its card is open again.
    function reconcile() {
      Object.keys(cards).forEach(function (key) {
        var card = cards[key];
        if (card.status === "added" && surveyIndex(card.itemId) === -1) {
          cards[key] = { status: "fresh" };
        }
      });
    }

    function act(focus, said) {
      focusKey = focus;
      survey.changed();
      if (live && said) { live.textContent = said; }
    }

    function addedAs(key) {
      return "Added as question " + (surveyIndex(cardOf(key).itemId) + 1) + ", not saved yet";
    }

    function add(key, text, batch) {
      cards[key] = { status: "added", itemId: survey.add(text), batch: batch || null };
    }

    function undo(key) {
      var card = cardOf(key);
      if (card.status === "added") { survey.remove(card.itemId); }
      cards[key] = { status: "fresh" };
    }

    function addAll(gapId, open) {
      batchSeq += 1;
      open.forEach(function (entry) { add(entry.key, entry.q.text, batchSeq); });
      batches[gapId] = batchSeq;
      act("batch:" + gapId, "Added " + S.plural(open.length, "question") + ", not saved yet");
    }

    function undoAll(gapId, entries) {
      entries.forEach(function (entry) {
        if (cardOf(entry.key).batch === batches[gapId]) { undo(entry.key); }
      });
      delete batches[gapId];
      act(entries.length ? entries[0].key + ":add" : null, "Removed them from the survey");
    }

    // --- one card -----------------------------------------------------------------

    function settledCard(li, entry, card) {
      li.className = "draft-card is-" + card.status;
      var at = card.status === "added" ? surveyIndex(card.itemId) : -1;
      li.appendChild(bidi("p", "draft-q is-quiet", at === -1 ? entry.q.text : survey.items()[at].text));
      var line = el("p", "draft-settled");
      var said = "Dismissed";
      if (card.status === "added") {
        said = "Added as question " + (at + 1) +
          (survey.isSaved(card.itemId) ? "" : ", not saved yet");
      }
      line.appendChild(el("span", "draft-settled-text", said));
      line.appendChild(button("Undo", "quiet", function () {
        var was = cardOf(entry.key).status;
        undo(entry.key);
        act(entry.key + ":add", was === "added" ? "Removed from the survey" : "Restored");
      }, entry.key + ":undo"));
      li.appendChild(line);
    }

    function editingCard(li, entry, card) {
      li.className = "draft-card is-editing";
      var box = el("textarea", "draft-edit");
      box.setAttribute("dir", "auto");
      box.setAttribute("data-key", entry.key);
      box.value = card.editText;
      var label = el("label", "field");
      label.appendChild(document.createTextNode("Edit the question, then add it"));
      label.appendChild(box);
      li.appendChild(label);
      li.appendChild(bidi("p", "draft-why", entry.q.why));
      var actions = el("div", "draft-actions");
      var addEdited = button("Add edited question", "primary", function () {
        add(entry.key, box.value.trim());
        act(entry.key + ":undo", addedAs(entry.key));
      });
      addEdited.disabled = !box.value.trim();
      function cancel() {
        cards[entry.key] = { status: "fresh" };
        act(entry.key + ":edit");
      }
      box.addEventListener("input", function () {
        cards[entry.key] = { status: "editing", editText: box.value };
        addEdited.disabled = !box.value.trim();
      });
      box.addEventListener("keydown", function (event) {
        if (event.key === "Escape") { cancel(); }
      });
      actions.appendChild(addEdited);
      actions.appendChild(button("Cancel", "quiet", cancel));
      li.appendChild(actions);
      if (focusKey === entry.key + ":box") { toFocus = box; }
    }

    function freshCard(li, entry) {
      li.appendChild(bidi("p", "draft-q", entry.q.text));
      li.appendChild(bidi("p", "draft-why", entry.q.why));
      var actions = el("div", "draft-actions");
      actions.appendChild(button("Add to survey", "primary", function () {
        add(entry.key, entry.q.text);
        act(entry.key + ":undo", addedAs(entry.key));
      }, entry.key + ":add"));
      actions.appendChild(button("Edit, then add", "", function () {
        cards[entry.key] = { status: "editing", editText: entry.q.text };
        focusKey = entry.key + ":box";
        render();
      }, entry.key + ":edit"));
      actions.appendChild(button("Dismiss", "quiet", function () {
        cards[entry.key] = { status: "dismissed" };
        act(entry.key + ":undo", "Dismissed");
      }, entry.key + ":dismiss"));
      li.appendChild(actions);
    }

    function renderCard(entry) {
      var li = el("li", "draft-card");
      var card = cardOf(entry.key);
      if (card.status === "added" || card.status === "dismissed") {
        settledCard(li, entry, card);
      } else if (card.status === "editing") {
        editingCard(li, entry, card);
      } else {
        freshCard(li, entry);
      }
      return li;
    }

    // --- one gap --------------------------------------------------------------------

    function gapHead(section, gap) {
      var head = el("div", "gap-head");
      head.appendChild(el("span", "gap-id", gap.gap_id));
      var open = !!expanded[gap.gap_id];
      var statement = bidi("button", "gap-statement" + (open ? " is-open" : ""),
        gap.statement || "(no statement)");
      statement.type = "button";
      statement.title = gap.statement || "";
      statement.setAttribute("aria-expanded", open ? "true" : "false");
      statement.addEventListener("click", function () {
        expanded[gap.gap_id] = !open;
        focusKey = "gap:" + gap.gap_id;
        render();
      });
      if (focusKey === "gap:" + gap.gap_id) { toFocus = statement; }
      head.appendChild(statement);
      if (gap.kind) { head.appendChild(el("span", "gap-chip chip-" + gap.kind, S.chip(gap))); }
      section.appendChild(head);
      if (!open) { return; }
      var detail = el("div", "gap-detail");
      if (S.next(gap.kind)) { detail.appendChild(el("p", "gap-next", S.next(gap.kind))); }
      if (gap.falsifier) {
        detail.appendChild(el("p", "gap-falsifier-label", "It would be false if:"));
        detail.appendChild(bidi("p", "gap-falsifier-text", gap.falsifier));
      }
      section.appendChild(detail);
    }

    function gapBatch(section, gap, entries) {
      var batched = entries.filter(function (entry) {
        var card = cardOf(entry.key);
        return card.status === "added" && batches[gap.gap_id] && card.batch === batches[gap.gap_id];
      });
      if (batched.length) {
        var line = el("p", "gap-batch");
        var saved = batched.every(function (entry) { return survey.isSaved(cardOf(entry.key).itemId); });
        line.appendChild(el("span", "", "Added " + S.plural(batched.length, "question") +
          (saved ? "" : ", not saved yet")));
        line.appendChild(button("Undo adding all", "quiet", function () { undoAll(gap.gap_id, batched); },
          "batch:" + gap.gap_id));
        section.appendChild(line);
        return;
      }
      var open = entries.filter(function (entry) { return cardOf(entry.key).status === "fresh"; });
      if (open.length < 2) { return; }
      // The gap id stays out of the visible label (it is the operator's own
      // text); the accessible name carries it for a listener out of context.
      var all = button("Add all " + open.length, "quiet", function () { addAll(gap.gap_id, open); });
      all.setAttribute("aria-label", "Add all " + open.length + " questions for gap " + gap.gap_id);
      section.appendChild(el("p", "gap-batch")).appendChild(all);
    }

    function renderGap(gap, entries) {
      var section = el("section", "draft-gap");
      gapHead(section, gap);
      gapBatch(section, gap, entries);
      var list = el("ul", "draft-cards");
      entries.forEach(function (entry) { list.appendChild(renderCard(entry)); });
      section.appendChild(list);
      return section;
    }

    // Prep's order for the gaps; a question naming a gap the payload does not
    // list still appears, under its own id, after them.
    function grouped(entries) {
      var known = {};
      var order = [];
      (draft.gaps || []).forEach(function (gap) {
        known[gap.gap_id] = gap;
        order.push(gap.gap_id);
      });
      var byGap = {};
      entries.forEach(function (entry) {
        var id = entry.q.gap_id;
        if (!known[id]) {
          known[id] = { gap_id: id, statement: entry.q.statement || "", kind: "" };
          order.push(id);
        }
        (byGap[id] = byGap[id] || []).push(entry);
      });
      return order.filter(function (id) { return byGap[id]; })
        .map(function (id) { return { gap: known[id], entries: byGap[id] }; });
    }

    // --- the panel ------------------------------------------------------------------

    function renderFresh() {
      var entries = offered();
      var counts = { added: 0, dismissed: 0 };
      entries.forEach(function (entry) {
        var status = cardOf(entry.key).status;
        if (counts[status] !== undefined) { counts[status] += 1; }
      });
      var head = el("div", "drafts-head");
      head.appendChild(el("h3", "drafts-title", "Drafted questions for your gaps"));
      if (entries.length) {
        head.appendChild(el("p", "drafts-count", S.counter(entries.length, counts.added, counts.dismissed)));
      }
      container.appendChild(head);
      if (draft.mock_label) {
        container.appendChild(el("p", "drafts-mock", String(draft.mock_label).replace(/:\s*$/, "")));
      }
      if (!entries.length) {
        container.appendChild(el("p", "drafts-line", S.ALL_ASKED));
        return;
      }
      container.appendChild(el("p", "drafts-hint", "Adding a question puts it at the end of the survey " +
        "below. Nothing is written until you press Save survey."));
      grouped(entries).forEach(function (group) {
        container.appendChild(renderGap(group.gap, group.entries));
      });
    }

    function render() {
      if (!container) { return; }
      // A survey change elsewhere re-renders this panel: an open edit box
      // keeps the focus it had.
      var active = document.activeElement;
      var editing = active && active.getAttribute && active.getAttribute("data-key");
      if (editing && !focusKey) { focusKey = editing + ":box"; }
      container.textContent = "";
      toFocus = null;
      if (!draft) {
        container.hidden = true;
        return;
      }
      container.hidden = false;
      if (draft.state === "fresh") {
        reconcile();
        renderFresh();
      } else {
        S.renderLine(document, container, draft);
      }
      focusKey = null;
      if (toFocus && toFocus.focus) { toFocus.focus(); }
    }

    function load(payload) {
      draft = payload || null;
      cards = {};
      batches = {};
      render();
    }

    return { load: load, render: render };
  }

  return { create: create };
})();
