CONSTRAINTS = """CREATE CONSTRAINT project_slug IF NOT EXISTS
FOR (p:Project)
REQUIRE p.slug IS UNIQUE;

CREATE CONSTRAINT source_id IF NOT EXISTS
FOR (s:Source)
REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT source_span_id IF NOT EXISTS
FOR (s:SourceSpan)
REQUIRE s.id IS UNIQUE;

CREATE CONSTRAINT chunk_id IF NOT EXISTS
FOR (c:Chunk)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT knowledge_chunk_id IF NOT EXISTS
FOR (c:KnowledgeChunk)
REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT assertion_id IF NOT EXISTS
FOR (a:Assertion)
REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT entity_id IF NOT EXISTS
FOR (e:Entity)
REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT graphify_node_id IF NOT EXISTS
FOR (g:GraphifyNode)
REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT graphify_edge_id IF NOT EXISTS
FOR (g:GraphifyEdge)
REQUIRE g.id IS UNIQUE;

CREATE CONSTRAINT domain_id IF NOT EXISTS
FOR (d:Domain)
REQUIRE d.id IS UNIQUE;

CREATE CONSTRAINT dataset_id IF NOT EXISTS
FOR (d:Dataset)
REQUIRE d.id IS UNIQUE;
"""

EXPLORE_QUERIES = """// Company Ontology Agent demo queries

// 1. Curated explorable graph, excluding provenance internals
MATCH p=(a:DemoNode)-[r]->(b:DemoNode)
WHERE NOT a:Source AND NOT b:Source
  AND NOT a:SourceSpan AND NOT b:SourceSpan
  AND NOT a:Assertion AND NOT b:Assertion
  AND NOT a:GraphifyNode AND NOT b:GraphifyNode
  AND NOT a:GraphifyEdge AND NOT b:GraphifyEdge
RETURN p
LIMIT 200;

// 2. No-query Explore fallback: Project connected to demo entities
MATCH p=(:DemoProject)-[:HAS_ENTITY]->(:DemoNode)
RETURN p
LIMIT 200;

// 3. Manager-ready architecture overview
MATCH p=(overview:System {name: "Architecture Overview"})-[*1..2]->(n)
RETURN p
LIMIT 200;

// 4. Backend, frontend, data, and deployment modules
MATCH p=(m:Module)-[r]->(n)
RETURN p
LIMIT 200;

// 5. API endpoints and their owning files/modules
MATCH p=(owner)-[r:EXPOSES|DEFINES]->(api:APIEndpoint)
RETURN p
LIMIT 100;

// 6. Data model and persistence graph
MATCH p=(n)-[r:READS_FROM|WRITES_TO|STORES_IN|DEFINES|CONTAINS]->(d)
WHERE d:DataModel OR d:Database OR d:DataStore OR n:DataModel OR n:Database OR n:DataStore
RETURN p
LIMIT 150;

// 7. Technology stack
MATCH p=(n)-[r:USES|RUNS_ON|DEPENDS_ON|DEPLOYS_TO]->(t:Technology)
RETURN p
LIMIT 150;

// 8. Graphify raw graph layer
MATCH p=(a:GraphifyNode)-[r:GRAPHIFY_RELATES]->(b:GraphifyNode)
RETURN p
LIMIT 200;

// 9. Relationship and label counts
MATCH ()-[r]->()
RETURN type(r) AS relationship, count(*) AS count
ORDER BY count DESC;
"""
