"""The project knowledge base (backlog B1): everything a project
already knows -- its own interviews, conversations recorded elsewhere, emails,
research and code -- indexed under `projects/<node>/knowledge/` so later steps
(search, synthesis, prep, the mirror) can cite it.

Offline by construction: adding, listing, searching and topic listing read and
write only the local disk. Nothing in this package calls a model or a vendor.
"""
