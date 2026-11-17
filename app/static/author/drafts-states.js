// app/static/author/drafts-states.js -- the words of the drafted-questions
// panel, and its one-line states (no draft yet, out of date, unreadable,
// unavailable, no gaps). Loaded before drafts.js, and leaves one global,
// `AuthorDraftStates`.
//
// Bidi: a reason from the server is its own dir="auto" element, never spliced
// into an English sentence, because it may carry a hypothesis or a file name.
var AuthorDraftStates = (function () {
  "use strict";

  var DOT = " · ";

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  var CHIP = {
    contested: function (g) { return "contested" + DOT + g.for + " for / " + g.against + " against"; },
    untested: function () { return "untested" + DOT + "no interview yet"; },
    "no-criterion": function () { return "no decision criterion"; },
    "only-unclear": function (g) { return "only unclear" + DOT + plural(g.unclear, "interview"); },
    thin: function (g) { return "thin" + DOT + plural(g.interviews, "interview"); },
  };

  var NEXT = {
    contested: "Evidence points both ways. Find what differs between the people on each side.",
    untested: "No interview has borne on it yet. Aim a question at what would prove it false.",
    "no-criterion": "Write a decision criterion under Hypotheses below before the next interview, " +
      "or no answer can settle it.",
    "only-unclear": "Only unclear evidence so far. Ask for a specific recent occasion.",
    thin: "Too few interviews have borne on it to call it either way.",
  };

  // Each state: what is wrong, then what to do. The reason, when there is
  // one, sits between them on its own line.
  var AGAIN = "Run this, add --yes to draft them again, then reload this page.";
  var LINES = {
    absent: ["No questions drafted yet.", "This command shows what it would send and calls nothing; " +
      "add --yes to draft them, then reload this page."],
    stale: ["The drafted questions are out of date.", AGAIN],
    unreadable: ["The drafted questions could not be read.", AGAIN],
    unavailable: ["The drafted questions cannot be shown.", "Run this to see the full error."],
  };
  var NO_GAPS = "No open gaps to draft questions for. An untested, contested or thin hypothesis shows up here.";
  var ALL_ASKED = "Every drafted question is already in your survey.";

  function chip(gap) {
    var said = CHIP[gap.kind];
    return said ? said(gap) : gap.kind;
  }

  function counter(drafted, added, dismissed) {
    return drafted + " drafted" + DOT + added + " added" + DOT + dismissed + " dismissed";
  }

  function el(document, tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  function copyButton(document, command, note) {
    var b = el(document, "button", "quiet", "Copy");
    b.type = "button";
    function say(text) { note.textContent = text; }
    b.addEventListener("click", function () {
      var clip = typeof navigator !== "undefined" && navigator && navigator.clipboard;
      if (!clip || !clip.writeText) { return say("Copy is not available here: select the command and copy it."); }
      clip.writeText(command).then(function () { say("Copied."); },
        function () { say("Copy failed: select the command and copy it."); });
    });
    return b;
  }

  // A calm line in place of the cards: what happened, and the exact command.
  function renderLine(document, container, draft) {
    if (draft.state === "no-gaps") {
      container.appendChild(el(document, "p", "drafts-line", NO_GAPS));
      return;
    }
    var said = LINES[draft.state] || LINES.unavailable;
    container.appendChild(el(document, "p", "drafts-line", said[0]));
    if (draft.reason && draft.state !== "absent") {
      var reason = el(document, "p", "drafts-reason", draft.reason);
      reason.setAttribute("dir", "auto");
      container.appendChild(reason);
    }
    container.appendChild(el(document, "p", "drafts-line", said[1]));
    var command = draft.project_command || draft.command;
    var row = el(document, "div", "drafts-command");
    row.appendChild(el(document, "code", "", command));
    var note = el(document, "span", "drafts-note");
    note.setAttribute("role", "status");
    row.appendChild(copyButton(document, command, note));
    row.appendChild(note);
    container.appendChild(row);
  }

  return {
    plural: plural, chip: chip, next: function (kind) { return NEXT[kind] || ""; },
    counter: counter, renderLine: renderLine, ALL_ASKED: ALL_ASKED,
  };
})();
