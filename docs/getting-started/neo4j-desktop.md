# Neo4j Desktop

Neo4j is the canonical graph backend for real runs.

## Expected Local Settings

The generated `project.yaml` defaults to:

```yaml
graph:
  backend: neo4j
  uri: bolt://localhost:7687
  uri_env: NEO4J_URI
  database: neo4j
  database_env: NEO4J_DATABASE
  username_env: NEO4J_USER
  password_env: NEO4J_PASSWORD
  write_visual_relationships: true
```

## Start Neo4j Desktop

1. Open Neo4j Desktop.
2. Start the target DBMS.
3. Confirm Bolt is enabled.
4. Confirm the Bolt port is `7687`.
5. Confirm the database name is `neo4j`, or update `project.yaml`.

## Configure Credentials

In the shell where you run the agent:

```bash
export NEO4J_USER=neo4j
export NEO4J_PASSWORD='your-password'
```

## Verify Connectivity

From the generated project directory:

```bash
make doctor
make publish-prune
make verify-visuals
```

`make publish-prune` runs checks, ingestion, Graphify, extraction, validation,
resolution, Neo4j writes, stale marking, and wiki export.

## Inspect The Graph

Counts:

```cypher
MATCH (n)
RETURN labels(n) AS labels, count(*) AS count
ORDER BY count DESC;
```

Relationship counts:

```cypher
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(*) AS count
ORDER BY count DESC;
```

Curated demo graph:

```cypher
MATCH p=(a:DemoNode)-[r]->(b:DemoNode)
WHERE NOT a:Source AND NOT b:Source
  AND NOT a:SourceSpan AND NOT b:SourceSpan
  AND NOT a:Assertion AND NOT b:Assertion
  AND NOT a:GraphifyNode AND NOT b:GraphifyNode
  AND NOT a:GraphifyEdge AND NOT b:GraphifyEdge
RETURN p
LIMIT 200;
```

Domain and dataset graph:

```cypher
MATCH p=(:Project)-[:HAS_DOMAIN]->(:Domain)-[:HAS_DATASET]->(:Dataset)-[:HAS_ENTITY]->(:Entity)
RETURN p
LIMIT 200;
```

Stale generated items:

```cypher
MATCH (n {stale: true})
RETURN labels(n) AS labels, n.name AS name, n.id AS id
LIMIT 50;
```

Architecture modules:

```cypher
MATCH p=(m:Module)-[r]->(n)
RETURN p
LIMIT 150;
```

When `write_visual_relationships` is true, the agent writes these derived entity-to-entity relationships while keeping `Assertion` nodes as canonical truth.

## No-Query Explore Setup

Published graphs include `DemoNode` labels, `caption` properties, direct
`DemoProject -> DemoNode` links, and curated entity-to-entity relationships. The
fastest no-query path is:

1. Open Neo4j Explore.
2. Click the `DemoNode` category/label.
3. Set node text/caption to `caption` if labels are hidden.
4. Expand relationships from the visible nodes.

Neo4j Desktop Explore does not always choose the right captions by default. In the
right panel, set node text/caption to `caption` for these labels:

- `DemoNode`
- `DemoProject`
- `Project`
- `Module`
- `System`
- `Technology`
- `APIEndpoint`
- `DataModel`
- `Database`
- `File`

Then open `graph/explore.cypher` from the generated project and paste query 1 for
the curated graph. `NEO4J_EXPLORE_GUIDE.md` contains the same guidance in the project.

If Explore shows only `Project`, `Source`, or `SourceSpan`, nothing is necessarily wrong.
Those are provenance labels. The curated demo graph is the entity-to-entity projection
returned by query 1.
