# Data Model

## Principle

The graph is assertion-centric. Extracted facts are not written directly as unquestioned truth.

Each fact is represented as an `Assertion` with:

- provenance,
- confidence,
- status,
- extractor metadata,
- evidence span,
- timestamps,
- classification.

## Core Nodes

- `Project`
- `Source`
- `SourceSpan`
- `Chunk`
- `Entity`
- `Person`
- `Organization`
- `Technology`
- `Concept`
- `Decision`
- `Requirement`
- `Issue`
- `Task`
- `Assertion`

Concrete entity types are represented as labels in Neo4j and as `EntityType` values in Python.

## Core Relationships

```text
(:Project)-[:HAS_SOURCE]->(:Source)
(:Source)-[:HAS_SPAN]->(:SourceSpan)
(:Chunk)-[:DERIVED_FROM]->(:SourceSpan)

(:Project)-[:HAS_ASSERTION]->(:Assertion)
(:Assertion)-[:SUBJECT]->(:Entity)
(:Assertion)-[:OBJECT]->(:Entity)
(:Assertion)-[:EVIDENCED_BY]->(:SourceSpan)
```

## Assertion Statuses

- `candidate`
- `validated`
- `rejected`
- `superseded`
- `disputed`

Only validated assertions are written by the current validation path.

## Generated Constraints

The scaffold generates Neo4j uniqueness constraints for:

- `Project.slug`
- `Source.id`
- `SourceSpan.id`
- `Chunk.id`
- `Assertion.id`
- `Entity.id`
