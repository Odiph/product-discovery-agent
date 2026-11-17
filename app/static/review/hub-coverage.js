// The hub's survey coverage section: this interview, and the project standing.
//
// textContent only, like review.js, which hands each payload here. Where the
// reading of an interview came from decides what its silence means
// (`app/web/review_coverage.py`): a LIVE record can say a question was not
// asked; the model's reading, the word match and an unread interview cannot,
// so their remainder is "not found, check by hand" and never "never asked",
// the same one-way rule `prep` keeps. `HubLines.coverageSources` is the one
// place the count of interviews with no live record is worded, so this
// section and its bottom line cannot disagree.
(function () {
  "use strict";

  var NO_LIVE = "This interview has no live coverage record (imported, or the coach was off), so a question "
    + "not found below may still have been asked.";
  var READ_FROM = {
    model: "read from the transcript by the model (python -m app coverage). The model can miss a question too.",
    words: "matched by words against the guide's wording, which misses a question asked in other words. "
      + "python -m app coverage has the model read it instead."
  };

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function questionList(items, className) {
    var list = el("ul", "questions " + className);
    items.forEach(function (item) { list.appendChild(el("li", null, item.text)); });
    return list;
  }

  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

  function listed(host, heading, items, className) {
    if (!items || !items.length) { return; }
    host.appendChild(el("h3", null, heading));
    host.appendChild(questionList(items, className));
  }

  function liveSession(session, host, note) {
    note.textContent = session.asked.length + " of " + session.total
      + " survey questions were asked in this interview.";
    listed(host, "Asked", session.asked, "asked");
    listed(host, "Not asked", session.unasked, "unasked");
  }

  function readSession(session, host, note) {
    if (session.source === "untracked") {
      note.textContent = "This interview has no live coverage record (imported, or the coach was off), and none "
        + "of your turns matched a survey question by words, so which survey questions it asked is not known: "
        + "check it by hand. python -m app coverage has the model read it.";
      return;
    }
    note.textContent = session.asked.length + " of " + session.total
      + " survey questions were found in this interview, " + READ_FROM[session.source];
    host.appendChild(el("p", "flag", NO_LIVE));
    listed(host, "Asked", session.asked, "asked");
    listed(host, "Not found (check by hand)", session.not_found, "not-found");
  }

  function drawSession(session, host, note) {
    if (!session || !session.reportable) {
      // NOT "0 of 0 covered". A call that ran without a survey did not miss
      // anything; it is the common path and must not read as a failing score.
      note.textContent = session ? "This interview ran without a survey, so there is nothing to have covered."
        : "No interview selected.";
      return;
    }
    if (READ_FROM[session.source] || session.source === "untracked") { readSession(session, host, note); }
    else { liveSession(session, host, note); }
    if (session.survey_source === "project") {
      // Today's wording attached to last month's answer is a silent lie.
      host.appendChild(el("p", "flag",
        "This interview stored no survey of its own, so the wording here is today's: it may have been edited "
        + "since the call."));
    }
    if ((session.orphaned_question_ids || []).length) {
      host.appendChild(el("p", "flag", "Asked, but no longer in the survey: " + session.orphaned_question_ids.join(", ")));
    }
  }

  function allLive(project, host) {
    var where = " in any of the " + plural(project.sessions_read, "interview") + " under this project.";
    var never = project.never_asked || [];
    if (!never.length) {
      host.appendChild(el("p", "note", "Every survey question has been asked at least once across "
        + plural(project.sessions_read, "interview") + "."));
      return;
    }
    host.appendChild(el("p", "note", never.length
      + (never.length === 1 ? " question has" : " questions have") + " never been asked" + where));
    host.appendChild(questionList(never, "unasked"));
  }

  function someUnread(project, from, host) {
    var missing = project.not_found || [];
    if (!missing.length) {
      host.appendChild(el("p", "note", "Every survey question has been asked at least once across "
        + plural(project.sessions_read, "interview") + " (" + from.unread + " with no live record: "
        + from.breakdown + ")."));
      return;
    }
    host.appendChild(el("p", "note", missing.length + (missing.length === 1 ? " question was" : " questions were")
      + " not found in any of the " + plural(project.sessions_read, "interview") + " under this project. "
      + from.unread + " of them " + (from.unread === 1 ? "has" : "have") + " no live record ("
      + from.breakdown + "), and a question they did not "
      + "show may still have been asked: check by hand before moving or dropping it."));
    host.appendChild(questionList(missing, "not-found"));
  }

  function drawProject(project, host) {
    var from = window.HubLines.coverageSources(project);
    var missing = (from.unread ? project.not_found : project.never_asked) || [];
    var heading = !missing.length ? "Covered across the project"
      : (from.unread ? "Not found across the project" : "Still unasked across the project");
    host.appendChild(el("h3", null, heading));
    if (from.unread) { someUnread(project, from, host); }
    else { allLive(project, host); }
    if (project.reading_note) { host.appendChild(el("p", "flag", project.reading_note)); }
  }

  function render(coverage, host, note) {
    if (!coverage) { note.textContent = ""; return; }
    if (coverage.error) { note.textContent = "Coverage could not be read: " + coverage.error; return; }
    drawSession(coverage.session, host, note);
    if (coverage.project) { drawProject(coverage.project, host); }
  }

  window.HubCoverage = { render: render };
}());
