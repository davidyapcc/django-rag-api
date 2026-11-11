# Owner is denormalised onto Chunk

Retrieval is the one query where a cross-Owner leak would be both easy to write and costly, so `Chunk` carries its own `owner` column and the similarity search filters on it in the same SQL statement (`Chunk.objects.filter(owner=...)` ordered by cosine distance). We rejected scoping through a join to `Document.owner`: it works, but it makes isolation depend on every future query remembering the join, and it gives the planner a harder query to combine with the HNSW index.

## Consequences

- A composite foreign key, `(document_id, owner_id)` → `Document(id, owner_id)` (migration `documents/0003`), makes the database reject a Chunk whose Owner differs from its Document's. It exists only in SQL because Django can't model it, so it won't appear in the model's state; don't drop it while tidying migrations.
- The key is `ON UPDATE CASCADE`, so if a Document ever changes Owner (not supported today), its Chunks follow in the same statement.
