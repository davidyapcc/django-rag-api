# Streaming answers

Answers are returned whole, after Citations have been checked. There is no Server-Sent Events or token streaming.

## Why this is out of scope

The core promise is that the client never sees a Citation the server can't back up: model output is parsed as structured JSON, and cited ids are filtered against what was actually retrieved **after** the whole answer exists. Streaming would show sentences and their claims before that check has run. That leaves two choices: stream unverified text and attach Citations at the end, or give up structured output and parse partial JSON. Both weaken the guarantee the project is built to show.

The cost isn't worth it at this answer length. Answers are a few sentences, so streaming would barely change how fast they feel. It would also bring partial-JSON parsing, spend that must still be recorded when the client disconnects mid-stream, a different gunicorn worker class (one sync worker per open stream would tie up half the free instance), and an HTMX SSE extension to vendor.

## What would reopen it

Answers becoming long enough (for example, multi-paragraph summaries) that time-to-first-token matters, together with a design that shows verified Citations alongside the text without showing unverified claims as final.

## Prior requests

- README roadmap: "Streaming answers (SSE)" (removed during triage, Nov 2026)
