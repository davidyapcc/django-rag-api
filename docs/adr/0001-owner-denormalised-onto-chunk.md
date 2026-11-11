# Owner is denormalised onto Chunk

Retrieval is the one query where a cross-Owner leak would be both easy to write and costly, so `Chunk` carries its own `owner` column and the similarity search filters on it in the same SQL statement (`Chunk.objects.filter(owner=...)` ordered by cosine distance). We rejected scoping through a join to `Document.owner`: it works, but it makes isolation depend on every future query remembering the join, and it gives the planner a harder query to combine with the HNSW index.

## Consequences

- Every code path that creates a Chunk must set `owner` to its Document's Owner. Nothing in the schema enforces that they match, so a mismatch would silently show a Chunk to the wrong Owner. Tests guard it, not the database.
- Moving a Document to another Owner (not supported today) would have to rewrite all of its Chunks too.
