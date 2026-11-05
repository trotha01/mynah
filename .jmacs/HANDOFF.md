# Handoff
## Objective
J workers list: every group (blocked included) ordered by UPDATED, most recent first; stamps parsed as real times; no stamp sorts last.
## Done
- Cause: roster sorted UPDATED as text (org "[2026-11-05 Thu 21:12]" from cloud-items.awk vs other formats), so mixed formats mis-ordered.
- companion.lisp sends "u" (UPDATED) per worker; index.html sortWorkers/stampMs sorts live first then blocked-with-no-worker, each by real time desc, no-stamp last.
- tests/test_workers_sort.js (node), screenshot docs/img/j-workers-sort-after.png.
## Pending
- Trevor local check; sbcl is not in the cloud, so companion.lisp change is untested (small format change).
## Next step
Reload J at http://127.0.0.1:8860/ (restart companion for the "u" field) and compare against a todo with blocked items.
