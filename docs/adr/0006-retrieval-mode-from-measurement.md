# ADR 0006: Default retrieval mode chosen by measurement (vector), not by convention

- **Status:** accepted, revisit when the corpus grows
- **Date:** 2026-11-04
- **Phase:** 2

## Context
Common advice is that hybrid (keyword + vector) retrieval beats either alone. project.md plans keyword vs vector vs hybrid with the comparison committed.

## Measurement
`evals/rag_compare.py` on 20 labelled questions, 7 leak probes, chunk sizes 300/600/1200 (`docs/evals/rag-comparison.md`):

| Mode | Recall@3 | Paraphrase recall@3 | Leaks |
|---|---|---|---|
| keyword | 0.85–0.90 | 0.67–0.78 | 0 |
| vector | 1.00 | 1.00 | 0 |
| hybrid (RRF) | 0.95 | 0.89 | 0 |

## Decision
Default `PgRetriever` mode is **vector** at chunk size 600. Hybrid and keyword stay available.

## Consequences and caveats
- The corpus is 7 documents, so recall@3 is easy and the comparison can't distinguish good from great. Hybrid usually wins on large corpora with jargon, ids and acronyms, where exact terms matter. Re-run the comparison whenever the corpus or the question set grows.
- The lesson is the method: decide from your own eval, record the numbers, and say when to revisit.
- The leak rate was 0 in every configuration because the filter is inside the SQL query, not because of the mode.
