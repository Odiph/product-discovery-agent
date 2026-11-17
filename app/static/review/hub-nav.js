// The hub's section nav, its "At a glance" block and every section's bottom
// line. Loaded BEFORE review.js and synthesis.js, which hand it each payload
// they render through `window.HubNav.publish(kind, data)`: the line is
// computed (hub-lines.js) from the very object the section was drawn from.
//
// Nav: three groups, "Opportunity tree", "This interview" and "Across interviews", as plain anchor
// links; the section in view is marked `aria-current` (IntersectionObserver).
// Changing interview keeps the reader in the section they were reading.
// textContent only; every browser global is read off `window` so the tests
// can stand in for it.
(function () {
  "use strict";

  var lines = window.HubLines;
  var collapse = window.HubCollapse;

  // In page order, which is also nav order. `glance: false` keeps a section
  // in the nav but out of the summary block: it is a form, not a finding.
  var SECTIONS = [
    { id: "sec-synthesis", key: "synthesis", label: "Opportunity tree", group: "tree" },
    { id: "sec-proposals", key: "proposals", label: "Proposals", group: "interview" },
    { id: "sec-standings", key: "standings", label: "Standings", group: "interview" },
    { id: "sec-add", key: "add", label: "Add a hypothesis", group: "interview", glance: false },
    { id: "sec-coverage", key: "coverage", label: "Survey coverage", group: "interview" },
    { id: "sec-numbers", key: "numbers", label: "In numbers", group: "interview" },
    { id: "sec-talk", key: "talk", label: "Who talked", group: "interview" },
    { id: "sec-transcript", key: "transcript", label: "Transcript", group: "interview" },
    { id: "sec-mirror", key: "mirror", label: "Mirror", group: "across" }
  ];
  var GROUPS = [{ key: "tree", title: "Opportunity tree" }, { key: "interview", title: "This interview" }, { key: "across", title: "Across interviews" }];
  var GLANCE_ID = "glance";
  var LOADING = "Loading.";
  var RESTORE_MS = 4000;
  var KEEP = { moments: 5, questions: 5, claims: 3 };

  /** The groups in order, each with its sections in page order. */
  function groups(sections) {
    return GROUPS.map(function (g) {
      return { key: g.key, title: g.title, sections: sections.filter(function (s) { return s.group === g.key; }) };
    });
  }

  /** The first section in page order now in view, or the previous one when none is. */
  function activeFrom(order, inView, previous) {
    for (var i = 0; i < order.length; i += 1) { if (inView[order[i]]) { return order[i]; } }
    return previous;
  }

  var doc = null;
  var state = {};
  var active = null;
  var restore = null;
  var restoreUntil = 0;

  function el(tag, className, text) {
    var node = doc.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function byId(id) { return doc ? doc.getElementById(id) : null; }

  function now() { return window.Date ? window.Date.now() : 0; }

  // --- building the nav and the glance block -----------------------------------------------

  function navLink(section) {
    var link = el("a", "nav-link");
    link.setAttribute("href", "#" + section.id);
    link.setAttribute("data-target", section.id);
    link.appendChild(el("span", "nav-label", section.label));
    if (section.key) {
      var count = el("span", "nav-count");
      count.setAttribute("id", "count-" + section.key);
      count.setAttribute("aria-hidden", "true");
      count.hidden = true;
      link.appendChild(count);
    }
    link.addEventListener("click", function () { restore = null; mark(section.id); });
    return link;
  }

  function buildNav(host) {
    host.textContent = "";
    host.appendChild(navLink({ id: GLANCE_ID, label: "At a glance" }));
    groups(SECTIONS).forEach(function (g) {
      var box = el("div", "nav-group " + g.key);
      var title = el("p", "nav-group-title", g.title);
      title.setAttribute("id", "navg-" + g.key);
      box.appendChild(title);
      var list = el("ul", "nav-list");
      list.setAttribute("aria-labelledby", "navg-" + g.key);
      g.sections.forEach(function (s) {
        var item = el("li");
        item.appendChild(navLink(s));
        list.appendChild(item);
      });
      box.appendChild(list);
      host.appendChild(box);
    });
  }

  function buildGlance(host) {
    host.textContent = "";
    groups(SECTIONS).forEach(function (g) {
      var box = el("div", "glance-group " + g.key);
      box.appendChild(el("h3", "glance-group-title", g.title));
      if (g.key === "interview") {
        var whole = el("p", "glance-group-line", LOADING);
        whole.setAttribute("id", "glance-interview");
        box.appendChild(whole);
      }
      var list = el("ul", "glance-list");
      g.sections.filter(function (s) { return s.glance !== false; }).forEach(function (s) {
        var item = el("li");
        var row = el("a", "glance-row");
        row.setAttribute("href", "#" + s.id);
        row.appendChild(el("span", "glance-name", s.label));
        var text = el("span", "glance-line", LOADING);
        text.setAttribute("id", "glance-" + s.key);
        row.appendChild(text);
        item.appendChild(row);
        list.appendChild(item);
      });
      box.appendChild(list);
      host.appendChild(box);
    });
  }

  // --- the section in view ------------------------------------------------------------------

  function links() { return collapse.findByClass(byId("hub-nav-links") || {}, "nav-link"); }

  function mark(id) {
    active = id;
    links().forEach(function (link) {
      if (link.getAttribute("data-target") === id) {
        link.setAttribute("aria-current", "location");
        keepInStrip(link);
      } else {
        link.removeAttribute("aria-current");
      }
    });
  }

  // On a narrow screen the links are one scrolling strip; keep the marked one in it.
  function keepInStrip(link) {
    var strip = byId("hub-nav-links");
    if (!strip || !(strip.scrollWidth > strip.clientWidth)) { return; }
    var left = link.offsetLeft, right = left + link.offsetWidth;
    if (left < strip.scrollLeft || right > strip.scrollLeft + strip.clientWidth) { strip.scrollLeft = Math.max(0, left - 24); }
  }

  function order() { return [GLANCE_ID].concat(SECTIONS.map(function (s) { return s.id; })); }

  function watch() {
    if (typeof window.IntersectionObserver !== "function") { return; }
    var inView = {};
    var observer = new window.IntersectionObserver(function (entries) {
      entries.forEach(function (e) { inView[e.target.id] = e.isIntersecting; });
      var next = activeFrom(order(), inView, active);
      if (next !== active) { mark(next); }
    }, { rootMargin: "-12% 0px -55% 0px", threshold: 0 });
    order().forEach(function (id) { var node = byId(id); if (node) { observer.observe(node); } });
  }

  // --- staying in the same section across an interview change ---------------------------------

  function jump(id) {
    var node = byId(id);
    if (node && node.scrollIntoView) { node.scrollIntoView({ block: "start", behavior: "instant" }); }
  }

  function holdPlace(id) {
    restore = id;
    restoreUntil = now() + RESTORE_MS;
  }

  function keepPlace() {
    if (!restore) { return; }
    if (now() > restoreUntil) { restore = null; return; }
    jump(restore);
  }

  // --- lines, counts and long lists ---------------------------------------------------------

  function setLine(key, text) {
    var line = byId("line-" + key);
    if (line) { line.textContent = text || ""; line.hidden = !text; }
    var row = byId("glance-" + key);
    if (row) { row.textContent = text || LOADING; }
  }

  function setCounts(map) {
    Object.keys(map).forEach(function (key) {
      var node = byId("count-" + key);
      if (!node) { return; }
      var n = map[key];
      node.textContent = n === null || n === undefined ? "" : String(n);
      node.hidden = n === null || n === undefined;
      var link = node.parentNode;
      var label = SECTIONS.filter(function (s) { return s.key === key; })[0].label;
      if (link && link.setAttribute) { link.setAttribute("aria-label", node.hidden ? label : label + ", " + n); }
    });
  }

  function cutColumns(hostId) {
    var host = byId(hostId);
    if (!host) { return; }
    collapse.findByClass(host, "column").forEach(function (col) {
      collapse.apply({ items: collapse.findByClass(col, "fact"), into: col, keep: KEEP.claims, noun: "claims",
        document: doc, pinned: function (n) { return (" " + n.className + " ").indexOf(" new ") !== -1; } });
    });
  }

  function cutQuestions() {
    var host = byId("coverage");
    if (!host) { return; }
    collapse.childrenTagged(host, "UL").forEach(function (list) {
      collapse.apply({ items: collapse.childrenTagged(list, "LI"), into: list, keep: KEEP.questions,
        noun: "questions", document: doc });
    });
  }

  function cutMoments() {
    var host = byId("mirror");
    if (!host) { return; }
    collapse.findByClass(host, "mirror-walked").forEach(function (box) {
      collapse.apply({ items: collapse.findByClass(box, "mirror-moment"), into: box, keep: KEEP.moments,
        noun: "moments", document: doc });
    });
  }

  var INTERVIEW_KEYS = ["proposals", "standings", "add", "coverage", "numbers", "talk", "transcript", "interview"];
  var UNLOADED = "This interview could not be loaded.";

  /** Blanks everything about the interview on screen: called the moment it changes. */
  function reset() {
    delete state.review;
    // Followers (the tree's marks) drop the old interview too, and a late `on` must not replay it.
    delete seen.review;
    (listeners.review || []).slice().forEach(function (fn) { tell(fn, null); });
    setTreeLine();
    INTERVIEW_KEYS.forEach(function (key) { setLine(key, ""); });
    setCounts({ proposals: null, standings: null, transcript: null });
  }

  /** The tree's line names this interview's marks, so it follows both payloads. */
  function setTreeLine() {
    if (!("synthesis" in state)) { return; }
    var review = state.review;
    var sessionId = review && !review.error ? review.session_id : null;
    setLine("synthesis", lines.synthesis(state.synthesis, sessionId));
  }

  function onReview(data) {
    setLine("proposals", "");
    setCounts({ proposals: null });
    setTreeLine();
    if (!data || data.error) {
      INTERVIEW_KEYS.forEach(function (key) { setLine(key, UNLOADED); });
      return;
    }
    var s = data.standings || [];
    setLine("standings", lines.standings(s, data.session_id));
    setLine("add", lines.addHypothesis(s));
    setLine("coverage", lines.coverage(data.coverage));
    setLine("numbers", lines.numbers(data.summary, data.session_id));
    setLine("talk", lines.talk(data.talk_share));
    setLine("transcript", lines.transcript(data.transcript));
    setLine("interview", lines.interview(data.extraction, s, data.session_id));
    setCounts(lines.counts("review", data));
    cutColumns("standings");
    cutQuestions();
  }

  var HANDLERS = {
    review: onReview,
    proposals: function (data) {
      setLine("proposals", lines.proposals(data, ((state.review || {}).standings) || []));
      setCounts(lines.counts("proposals", data));
      cutColumns("proposals");
    },
    mirror: function (data) {
      // The mirror is fetched after the review; a mirror with no review before it
      // means the review request itself failed, so the interview's lines say so.
      if (!state.review) { INTERVIEW_KEYS.forEach(function (key) { setLine(key, UNLOADED); }); }
      setLine("mirror", lines.mirror(data));
      cutMoments();
    },
    synthesis: function (data) { setTreeLine(); setCounts(lines.counts("synthesis", data)); }
  };

  /** Called by the section scripts with the payload they just rendered. */
  function publish(kind, data) {
    if (!HANDLERS[kind]) { return; }
    seen[kind] = { data: data };
    if (doc) {
      state[kind] = data;
      try {
        HANDLERS[kind](data);
      } catch (err) {
        // A summary is derived output: a payload it cannot read must never take
        // the section it summarises down with it.
        setLine(kind === "review" ? "standings" : kind, "This section could not be summarised.");
      }
      keepPlace();
    }
    (listeners[kind] || []).slice().forEach(function (fn) { tell(fn, data); });
  }

  // Other panels follow a payload too (the tree follows the interview). One
  // listener failing never stops the others, nor the publish.
  var listeners = {};
  var seen = {};
  function tell(fn, data) { try { fn(data); } catch (err) { /* a follower is derived output */ } }

  /** `fn(data)` after every publish of `kind`; once now when one already happened. */
  function on(kind, fn) {
    (listeners[kind] = listeners[kind] || []).push(fn);
    if (seen[kind]) { tell(fn, seen[kind].data); }
  }

  function init(documentRef) {
    doc = documentRef;
    var nav = byId("hub-nav-links");
    var glance = byId("glance-rows");
    if (!nav || !glance || !lines || !collapse) { doc = null; return; }
    buildNav(nav);
    buildGlance(glance);
    watch();
    var picker = byId("session-picker");
    if (picker) { picker.addEventListener("change", function () { holdPlace(active || GLANCE_ID); reset(); }); }
    var hash = window.location && window.location.hash ? window.location.hash.slice(1) : "";
    if (order().indexOf(hash) !== -1) { holdPlace(hash); mark(hash); }
    if (window.addEventListener) {
      // Any reading the operator starts cancels the hold, except on the picker itself.
      ["wheel", "touchmove", "keydown", "pointerdown"].forEach(function (type) {
        window.addEventListener(type, function (e) { if (!e || e.target !== picker) { restore = null; } }, { passive: true });
      });
    }
  }

  window.HubNav = {
    SECTIONS: SECTIONS, GROUPS: GROUPS, groups: groups, activeFrom: activeFrom,
    publish: publish, on: on, init: init, active: function () { return active; }
  };
  if (typeof document !== "undefined" && document && document.getElementById) { init(document); }
}());
