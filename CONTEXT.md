# Django RAG API

Document question answering: a person uploads documents and asks questions that are answered only from those documents, with citations.

## Language

### Content

**Owner**:
The user a Document, Chunk or Query belongs to. Nothing is ever visible across owners.
_Avoid_: Account, tenant, customer

**Document**:
One uploaded file, after its text has been extracted, chunked and embedded.
_Avoid_: File, upload, source

**Chunk**:
A contiguous slice of a Document's text with its embedding; the unit that is retrieved and cited.
_Avoid_: Passage, segment, snippet

**Sample documents**:
The fixed set of demo Documents a visitor can load with one click; the same corpus the eval uses.
_Avoid_: Fixtures, seed data

### Asking

**Query**:
One question, its answer, the Citations, and what it cost. Single-shot unless it is a Follow-up: a Query knows nothing about other Queries.
_Avoid_: Conversation, chat, message, turn

**Follow-up**:
A Query that names one earlier Query of the same Owner as its predecessor; a chain of Follow-ups is what a person would call a conversation. Its answer still rests only on Chunks retrieved for it, never on earlier answers.
_Avoid_: Conversation, thread, turn

**Citation**:
A Chunk the answer relied on. Only Chunks that were actually retrieved for that Query can be Citations.
_Avoid_: Source, reference

**Abstain**:
To answer "I don't know" with no Citations because nothing retrieved was relevant.
_Avoid_: Refuse, fail

### Demo

**Guest**:
An Owner created by one click with no sign-up, who expires 24 hours after creation along with everything they own.
_Avoid_: Anonymous user, demo account, trial user

**Demo budget**:
The global cap on LLM spend per UTC day across all Owners. Once it is reached, new Queries are declined until the next day.
_Avoid_: Quota, rate limit (a rate limit is per Owner)

**Allowance**:
The share of one UTC day's Demo budget a single Owner may spend. Once an Owner's Allowance is used up, their new Queries are declined even if the Demo budget has room.
_Avoid_: Quota, per-user budget, credit
