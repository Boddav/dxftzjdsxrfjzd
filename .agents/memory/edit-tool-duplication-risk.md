---
name: Edit tool large-file duplication risk
description: Edit calls against a large Flask admin file silently duplicated the entire file's content instead of applying a targeted patch.
---

While patching a ~1200+ line `admin_interface.py`, two consecutive `Edit` tool calls (each a normal unique old_string/new_string replacement) resulted in the whole file's content being duplicated end-to-end (routes, imports, `Flask(__name__)`, `logging.basicConfig`, everything appeared twice, then after a second edit, four times). `ast.parse` still succeeded because Python tolerates duplicate top-level defs/routes (last one wins), so the corruption wasn't caught by a syntax check alone — it was only caught by `grep -c "^@app.route"` and route-count sanity checks, and by the code-review subagent flagging duplicate-looking sections.

**Why:** Root cause unconfirmed (tool-side bug or a race with a concurrent file read), but it recurred twice in the same session on the same file.

**How to apply:** After any `Edit` on a large/critical file, immediately verify line count and a distinguishing marker count (e.g. `grep -c "^@app.route"` for Flask, or count of a known top-level symbol) against the expected pre-edit value to catch silent duplication early. If duplication is detected, restore the file from `git show HEAD:<path>` (or last known-good checkpoint) and reapply changes via a scripted Python find-and-replace (`content.replace(old, new)` with an assert on `count==1`) instead of the Edit tool, which sidestepped the recurrence.
