from __future__ import annotations

from pathlib import Path

from company_ontology_agent.config.project_config import default_config, write_project_config
from company_ontology_agent.graph.bootstrap import write_bootstrap_files
from company_ontology_agent.retrieval.questions import FLAGSHIP_QUESTIONS, NO_ANSWER_QUESTION
from company_ontology_agent.storage.local import ensure_project_dirs


def scaffold_project(
    target: Path,
    project_slug: str,
    *,
    with_docker: bool,
    force: bool,
) -> Path:
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"Target directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    ensure_project_dirs(target)
    write_project_config(default_config(project_slug), target / "project.yaml")
    write_bootstrap_files(target)
    _write_gitignore(target)
    _write_env_example(target)
    _write_ontology_defaults(target)
    _write_rag_questions(target)
    _write_makefile(target, with_docker=with_docker)
    _write_readme(target, project_slug)
    if with_docker:
        _write_docker_compose(target)
    return target


def _write_env_example(target: Path) -> None:
    (target / ".env.example").write_text(
        "# Neo4j (required for publish, indexing, and live Ask)\n"
        "NEO4J_URI=bolt://localhost:7687\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=ontology-password\n"
        "\n# OpenAI (required for Graphify/OpenAI and GraphRAG)\n"
        "OPENAI_API_KEY=\n"
        "ONTOLOGY_AGENT_LLM_MODEL=\n"
        "ONTOLOGY_AGENT_EMBEDDING_MODEL=\n",
        encoding="utf-8",
    )


def _write_gitignore(target: Path) -> None:
    (target / ".gitignore").write_text(
        "# Secrets\n"
        ".env\n\n"
        "# Python and local tooling\n"
        "__pycache__/\n"
        "*.py[cod]\n"
        ".pytest_cache/\n"
        ".ruff_cache/\n"
        ".mypy_cache/\n"
        ".venv/\n\n"
        "# Rebuildable pipeline artifacts\n"
        "data/raw/\n"
        "data/processed/\n"
        "*.sqlite\n"
        "*.sqlite3\n"
        "*.log\n\n"
        "# Rebuildable local demo portal\n"
        "portal/\n\n"
        "# Rebuildable GraphRAG measurements\n"
        "rag/evaluation.json\n"
        "rag/index-status.json\n"
        "rag/text2cypher-diagnostics.jsonl\n\n"
        "# Graphify intermediates\n"
        "graphify-out/**\n"
        "!graphify-out/\n"
        "!graphify-out/GRAPH_REPORT.md\n\n"
        "# Wiki markdown is intentionally committed.\n"
        "!wiki/\n"
        "!wiki/**/*.md\n",
        encoding="utf-8",
    )


def _write_docker_compose(target: Path) -> None:
    (target / "docker-compose.yml").write_text(
        "services:\n"
        "  neo4j:\n"
        "    image: neo4j:5-community\n"
        "    ports:\n"
        "      - \"127.0.0.1:7474:7474\"\n"
        "      - \"127.0.0.1:7687:7687\"\n"
        "    environment:\n"
        '      NEO4J_AUTH: "${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-ontology-password}"\n'
        "    volumes:\n"
        "      - neo4j-data:/data\n"
        "volumes:\n"
        "  neo4j-data:\n",
        encoding="utf-8",
    )


def _write_ontology_defaults(target: Path) -> None:
    (target / "ontology" / "core.ttl").write_text(
        "@prefix coa: <https://example.com/company-ontology-agent#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
        "coa:Project a owl:Class .\n"
        "coa:Source a owl:Class .\n"
        "coa:SourceSpan a owl:Class .\n"
        "coa:Chunk a owl:Class .\n"
        "coa:Entity a owl:Class .\n"
        "coa:Person rdfs:subClassOf coa:Entity .\n"
        "coa:Organization rdfs:subClassOf coa:Entity .\n"
        "coa:Technology rdfs:subClassOf coa:Entity .\n"
        "coa:Concept rdfs:subClassOf coa:Entity .\n"
        "coa:System rdfs:subClassOf coa:Entity .\n"
        "coa:Module rdfs:subClassOf coa:Entity .\n"
        "coa:Package rdfs:subClassOf coa:Entity .\n"
        "coa:File rdfs:subClassOf coa:Entity .\n"
        "coa:Class rdfs:subClassOf coa:Entity .\n"
        "coa:Function rdfs:subClassOf coa:Entity .\n"
        "coa:APIEndpoint rdfs:subClassOf coa:Entity .\n"
        "coa:DataModel rdfs:subClassOf coa:Entity .\n"
        "coa:Database rdfs:subClassOf coa:Entity .\n"
        "coa:DataStore rdfs:subClassOf coa:Entity .\n"
        "coa:Queue rdfs:subClassOf coa:Entity .\n"
        "coa:ExternalService rdfs:subClassOf coa:Entity .\n"
        "coa:DeploymentUnit rdfs:subClassOf coa:Entity .\n"
        "coa:Environment rdfs:subClassOf coa:Entity .\n"
        "coa:Config rdfs:subClassOf coa:Entity .\n"
        "coa:SecretRef rdfs:subClassOf coa:Entity .\n"
        "coa:Workflow rdfs:subClassOf coa:Entity .\n"
        "coa:UserRole rdfs:subClassOf coa:Entity .\n"
        "coa:Decision rdfs:subClassOf coa:Entity .\n"
        "coa:Requirement rdfs:subClassOf coa:Entity .\n"
        "coa:Issue rdfs:subClassOf coa:Entity .\n"
        "coa:Task rdfs:subClassOf coa:Entity .\n"
        "coa:BusinessEntity rdfs:subClassOf coa:Entity .\n"
        "coa:Assertion a owl:Class .\n",
        encoding="utf-8",
    )
    (target / "ontology" / "shapes.ttl").write_text(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix coa: <https://example.com/company-ontology-agent#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n"
        "coa:AssertionShape a sh:NodeShape ;\n"
        "  sh:targetClass coa:Assertion ;\n"
        "  sh:property [ sh:path coa:predicate ; sh:minCount 1 ; sh:datatype xsd:string ] ;\n"
        "  sh:property [ sh:path coa:confidence ; sh:minCount 1 ; "
        "sh:datatype xsd:decimal ; sh:minInclusive 0 ; sh:maxInclusive 1 ] ;\n"
        "  sh:property [ sh:path coa:status ; sh:minCount 1 ; "
        "sh:in (\"candidate\" \"validated\" \"rejected\" \"superseded\" \"disputed\") ] ;\n"
        "  sh:property [ sh:path coa:evidenceSpanId ; sh:minCount 1 ; "
        "sh:datatype xsd:string ] .\n\n"
        "coa:EntityShape a sh:NodeShape ;\n"
        "  sh:targetClass coa:Entity ;\n"
        "  sh:property [ sh:path coa:name ; sh:minCount 1 ; sh:datatype xsd:string ] ;\n"
        "  sh:property [ sh:path coa:entityType ; sh:minCount 1 ; sh:datatype xsd:string ] .\n",
        encoding="utf-8",
    )
    (target / "ontology" / "datasets").mkdir(parents=True, exist_ok=True)


def _write_rag_questions(target: Path) -> None:
    (target / "rag" / "questions.yaml").write_text(
        "# Expectations only: never add scripted answers or question-specific runtime logic.\n"
        "# Fill expected_entities with names from YOUR project before running rag evaluate.\n"
        "questions:\n"
        "  - id: downstream-impact\n"
        f"    question: {FLAGSHIP_QUESTIONS[0]}\n"
        "    expected_entities: []\n"
        "    expected_sources: []\n"
        "    expected_relationships: []\n"
        "    should_answer: true\n"
        "  - id: dependency-evidence\n"
        f"    question: {FLAGSHIP_QUESTIONS[1]}\n"
        "    expected_entities: []\n"
        "    expected_sources: []\n"
        "    expected_relationships: []\n"
        "    should_answer: true\n"
        "  - id: explicit-no-answer\n"
        f"    question: {NO_ANSWER_QUESTION}\n"
        "    expected_entities: []\n"
        "    expected_sources: []\n"
        "    expected_relationships: []\n"
        "    should_answer: false\n",
        encoding="utf-8",
    )


def _write_makefile(target: Path, *, with_docker: bool) -> None:
    docker_start = (
        "\t@if (echo > /dev/tcp/127.0.0.1/7687) >/dev/null 2>&1; then \\\n"
        "\t\techo \"Neo4j already available on 127.0.0.1:7687\"; \\\n"
        "\telse \\\n"
        "\t\tdocker compose up -d neo4j; \\\n"
        "\tfi\n"
        if with_docker
        else ""
    )
    docker_stop = "\tdocker compose stop neo4j\n" if with_docker else "\t@true\n"
    ensure_neo4j = docker_start or "\t@true\n"
    (target / "Makefile").write_text(
        "SHELL := /bin/bash\n"
        "ONTOLOGY_AGENT ?= ontology-agent\n"
        "-include .env\n"
        "export\n\n"
        ".PHONY: start refresh stop check evaluate reset clean-generated neo4j\n\n"
        "start: neo4j\n\t$(ONTOLOGY_AGENT) launch\n\n"
        "refresh: neo4j\n"
        "\t$(ONTOLOGY_AGENT) launch --no-serve\n\n"
        "neo4j:\n"
        f"{ensure_neo4j}\n"
        "stop:\n"
        f"{docker_stop}\n"
        "check:\n\t$(ONTOLOGY_AGENT) run --dry-run\n\n"
        "evaluate:\n\t$(ONTOLOGY_AGENT) rag evaluate\n\n"
        "reset:\n\t$(ONTOLOGY_AGENT) graph reset --yes\n\n"
        "clean-generated:\n\trm -rf data/processed wiki portal graphify-out "
        "rag/evaluation.json rag/index-status.json rag/text2cypher-diagnostics.jsonl\n",
        encoding="utf-8",
    )


def _write_readme(target: Path, project_slug: str) -> None:
    (target / "README.md").write_text(
        f"# {project_slug}\n\n"
        "## Start Ontology Atlas\n\n"
        "```bash\n"
        "cp .env.example .env\n"
        "# Configure .env and enable llm, embedding, and rag in project.yaml once.\n"
        "make start\n"
        "```\n\n"
        "`make start` ensures Neo4j is available and performs the initial build when needed, then "
        "serves the workspace. Later starts are immediate. Use `make refresh` after source or data "
        "changes. Press Ctrl+C to stop the portal and run `make stop` when finished.\n\n"
        "## Other Useful Commands\n\n"
        "```bash\n"
        "make refresh       # Rebuild without starting the portal server\n"
        "make check         # Offline validation\n"
        "make evaluate\n"
        "make stop\n"
        "```\n"
        "\n"
        "The `wiki/` folder is project-local and intended to be committed. "
        "`data/processed/` and Graphify internals are rebuildable "
        "and ignored by git. Use `make check` for offline validation, `make refresh` after "
        "source changes, and `make reset` only for a clean local Neo4j rebuild. "
        "Curate `rag/questions.yaml` "
        "before presenting the saved evaluation report.\n",
        encoding="utf-8",
    )
