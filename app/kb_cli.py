"""`python -m app kb ...`: the project knowledge base from the command line.

    kb add PATH... [--type T]   index files, folders, exports, a repository
    kb add --sessions           index this project's own interviews
    kb list [--type T]          what is indexed
    kb remove ID                drop one document (the index is local; the file is untouched)
    kb search "QUERY"           cited hits, each labelled with its source type
    kb topics [ID]              what each document, and the project, is about
    kb digest [--yes|--show]    summarise research and code for the live coach (lists only, without --yes)

Everything here reads and writes `projects/<node>/knowledge/` only, and
nothing here touches the project's facts, so `standing` is the same before
and after any `kb` command. Only `kb digest` sends anything anywhere: the
research and code documents it summarises go to the coach model, once per
change. Interviews, conversations and emails are never sent by it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from app import projects as projects_mod
from app.kb import digest as kb_digest
from app.kb import index as kb_index
from app.kb import sources
from app.kb.document import SOURCE_TYPES, SPOKEN_TYPES
from app.kb.store import KNOWLEDGE_DIR_NAME, KnowledgeStore, KnowledgeStoreError
from app.session.reader import list_session_ids

LOCAL_ONLY_NOTE = "Indexed on this machine only; nothing was sent anywhere."
DIGEST_NOTE = ("Research and code reach the live coach only through `kb digest`, which sends them "
               "to the coach model to summarise. Interviews, conversations and emails never do.")


def add_parsers(subparsers, add_project_argument: Callable[[argparse.ArgumentParser], None]) -> None:
    kb = subparsers.add_parser(
        "kb",
        help="The project knowledge base: past conversations, emails, research and code, searchable with citations",
    )
    actions = kb.add_subparsers(dest="kb_command", required=True)

    add = actions.add_parser("add", help="Index files or folders (re-adding unchanged content does nothing)")
    add.add_argument("paths", nargs="*", type=Path, help="files, folders, an .mbox export, or a repository")
    add.add_argument("--type", choices=SOURCE_TYPES, default=None,
                     help="override the detected source type")
    add.add_argument("--sessions", action="store_true", help="also index every interview filed in this project")

    listing = actions.add_parser("list", help="List indexed documents")
    listing.add_argument("--type", choices=SOURCE_TYPES, default=None)

    remove = actions.add_parser("remove", help="Remove one document from the index (the source file is untouched)")
    remove.add_argument("doc_id", help="a document id, or a unique prefix of one (see `kb list`)")

    search = actions.add_parser("search", help="Search with citations")
    search.add_argument("query")
    search.add_argument("--type", choices=SOURCE_TYPES, action="append", default=None,
                        help="only these source types (repeatable)")
    search.add_argument("--limit", type=int, default=kb_index.DEFAULT_LIMIT)

    topics = actions.add_parser("topics", help="Topics per document and across the project")
    topics.add_argument("doc_id", nargs="?", default=None)

    digest = actions.add_parser(
        "digest",
        help="Summarise research and code into cited notes for the live coach (a paid model call per changed document)",
    )
    digest_mode = digest.add_mutually_exclusive_group()
    digest_mode.add_argument("--show", action="store_true", help="print the notes the coach can draw on")
    digest_mode.add_argument("--yes", action="store_true",
                             help="send them: without it, `kb digest` only lists what it would send")

    for action in (add, listing, remove, search, topics, digest):
        add_project_argument(action)


def run(args: argparse.Namespace) -> int:
    from benchmark.console import use_utf8_console

    use_utf8_console()
    if args.project is None:
        print("ERROR: `kb` needs --project: knowledge belongs to a project node", file=sys.stderr)
        return 2
    paths = projects_mod.resolve(args.project)
    store = KnowledgeStore.for_node(paths.node_dir)
    _, damaged = store.scan()
    for name in damaged:
        print(f"WARNING: {name} in the knowledge base is damaged and was left out; "
              f"`kb add` its source again to repair it", file=sys.stderr)
    try:
        if args.kb_command == "add":
            return _add(args, store, paths)
        if args.kb_command == "list":
            return _list(store, args.type)
        if args.kb_command == "remove":
            removed = store.remove(args.doc_id)
            print(f"Removed {removed.doc_id}  {removed.document.title}  (the source itself is untouched)")
            return 0
        if args.kb_command == "search":
            return _search(store, args.query, args.type, args.limit)
        if args.kb_command == "digest":
            return _digest(args, store, paths.node_dir / KNOWLEDGE_DIR_NAME)
        return _topics(store, args.doc_id)
    except KnowledgeStoreError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _add(args: argparse.Namespace, store: KnowledgeStore, paths: projects_mod.ProjectPaths) -> int:
    targets = list(args.paths)
    if args.sessions:
        targets.extend(paths.sessions_root / session_id for session_id in list_session_ids(paths.sessions_root))
    if not targets:
        print("ERROR: nothing to add: give a path, or --sessions", file=sys.stderr)
        return 2
    outcomes = {"added": 0, "updated": 0, "unchanged": 0}
    skipped = 0
    for target in targets:
        loaded = sources.load(target, source_type=args.type)
        for document in loaded.documents:
            if not document.sections:
                print(f"skipped  {document.origin}: no text found")
                skipped += 1
                continue
            outcome = store.put(document)
            outcomes[outcome] += 1
            print(f"{outcome:9} {document.doc_id}  [{document.source_type}]  {document.title}"
                  f"  ({len(document.sections)} sections)")
        for skip in loaded.skipped:
            print(f"skipped  {skip.path}: {skip.reason}")
            skipped += 1
    print(f"\n{outcomes['added']} added, {outcomes['updated']} updated, {outcomes['unchanged']} unchanged, "
          f"{skipped} skipped -> projects/{paths.path}/{KNOWLEDGE_DIR_NAME}/")
    print(LOCAL_ONLY_NOTE)
    print(DIGEST_NOTE)
    return 0 if sum(outcomes.values()) or not skipped else 1


def _list(store: KnowledgeStore, source_type) -> int:
    stored = [s for s in store.all() if source_type is None or s.document.source_type == source_type]
    if not stored:
        print("The knowledge base is empty." if source_type is None else f"No {source_type} documents.")
        return 0
    for item in stored:
        document = item.document
        speakers = "  speakers" if document.source_type in SPOKEN_TYPES and document.has_speakers else ""
        print(f"{item.doc_id}  {document.source_type:12} {document.date or '----------'}  {document.title}"
              f"  ({len(document.sections)} sections{speakers})")
    print(f"\n{len(stored)} documents")
    return 0


def _search(store: KnowledgeStore, query: str, source_types, limit: int) -> int:
    index = kb_index.KeywordIndex(item.document for item in store.all())
    hits = index.search(query, limit=max(1, limit), source_types=source_types)
    if not hits:
        print("No matches." if index.chunk_count else "The knowledge base is empty: `kb add` something first.")
        return 0
    for hit in hits:
        who = f" -- {hit.speaker}" if hit.speaker else ""
        when = f" ({hit.date})" if hit.date else ""
        print(f"[{hit.source_type}] {hit.title}{when} -- {hit.location}{who}   [{hit.doc_id}]")
        print(f"    {hit.snippet}\n")
    return 0


def _topics(store: KnowledgeStore, doc_ref) -> int:
    documents = [item.document for item in store.all()]
    if not documents:
        print("The knowledge base is empty.")
        return 0
    per_document = kb_index.topics(documents)
    if doc_ref is not None:
        item = store.get(doc_ref)
        print(f"{item.doc_id}  {item.document.title}: {', '.join(per_document[item.doc_id]) or '(none)'}")
        return 0
    for document in documents:
        print(f"{document.doc_id}  [{document.source_type}] {document.title}: "
              f"{', '.join(per_document[document.doc_id]) or '(none)'}")
    shared = kb_index.project_topics(documents)
    print("\nAcross the project: " + (", ".join(f"{term} ({n})" for term, n in shared) or "(no topic shared by two documents yet)"))
    return 0


def _digest(args: argparse.Namespace, store: KnowledgeStore, knowledge_dir: Path) -> int:
    try:
        entries = kb_digest.load(knowledge_dir)
    except kb_digest.DigestError as exc:
        if not args.show:
            print(f"WARNING: {exc}; rebuilding it from scratch", file=sys.stderr)
            entries = ()
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if args.show:
        return _show_digest(entries)
    stored, damaged = store.scan()
    damaged_ids = frozenset(name.removesuffix(".json") for name in damaged)
    plan = kb_digest.plan(entries, (item.document for item in stored), damaged_ids=damaged_ids)
    if plan.not_digested:
        left_out = ", ".join(f"{n} {kind}" for kind, n in sorted(plan.not_digested.items()))
        print(f"Never digested (other people's words stay off the live prompt): {left_out}")
    if not plan.to_summarize:
        if plan.dropped:
            kb_digest.save(knowledge_dir, plan.kept)
            print(f"Dropped the notes of {len(plan.dropped)} removed document(s).")
        print(f"Nothing to summarise: {len(plan.kept)} document(s) already digested.")
        return 0
    return _summarise(args, plan, knowledge_dir)


def _summarise(args: argparse.Namespace, plan: "kb_digest.Plan", knowledge_dir: Path) -> int:
    from app.coach import reasoning_client
    from app.kb import digest_model

    calls = sum(len(digest_model.parts(document)) for document in plan.to_summarize)
    model = reasoning_client.resolve_extract_model()
    print(f"{len(plan.to_summarize)} document(s) to summarise, {calls} call(s) to {model}:")
    for document in plan.to_summarize:
        print(f"  [{document.source_type}] {document.title}  ({document.text_chars:,} chars)")
    if not args.yes:
        print("Nothing was sent. Check that none of these holds a customer's own words "
              "(a call transcript or an email saved as a document), then run again with --yes.")
        return 0
    try:
        client = reasoning_client.build_client()
    except reasoning_client.CoachConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    entries = list(plan.kept)
    failed = 0
    for document in plan.to_summarize:
        try:
            entry = digest_model.summarize(client, document, model=model)
        except digest_model.DigestFailure as exc:
            print(f"ERROR: {document.title}: the summary failed ({exc.reason}); "
                  f"its old notes are left out until it succeeds", file=sys.stderr)
            failed += 1
            continue
        entries.append(entry)
        # Saved after every document: a later failure must not cost the paid ones.
        kb_digest.save(knowledge_dir, entries)
        print(f"digested  {entry.doc_id}  {entry.title}: {len(entry.points)} note(s)")
    kb_digest.save(knowledge_dir, entries)
    print(f"\n{len(entries)} document(s) in the coach digest; {failed} failed.")
    return 1 if failed else 0


def _show_digest(entries) -> int:
    if not entries:
        print("No coach digest yet: run `kb digest`.")
        return 0
    for entry in entries:
        print(f"{entry.doc_id}  [{entry.source_type}] {entry.title}")
        for point in entry.points:
            print(f"    - {point.text}  ({point.location})")
    return 0
