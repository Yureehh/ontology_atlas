from __future__ import annotations

from pathlib import Path

from company_ontology_agent.config.project_config import default_config, write_project_config
from company_ontology_agent.graph.bootstrap import write_bootstrap_files
from company_ontology_agent.storage.local import ensure_project_dirs
from company_ontology_agent.storage.metadata import init_metadata_store


def scaffold_project(
    target: Path,
    project_slug: str,
    *,
    with_docker: bool,
    with_markdown_wiki: bool,
    force: bool,
) -> Path:
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"Target directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    ensure_project_dirs(target)
    init_metadata_store(target)
    write_project_config(default_config(project_slug), target / "project.yaml")
    write_bootstrap_files(target)
    _write_gitignore(target)
    _write_env_example(target)
    _write_ontology_defaults(target)
    _write_makefile(target)
    _write_scripts(target)
    _write_readme(target, project_slug, with_docker, with_markdown_wiki)
    if with_docker:
        _write_docker_compose(target)
    if with_markdown_wiki:
        (target / "wiki" / "index.md").write_text(f"# {project_slug} Wiki\n", encoding="utf-8")
    return target


def _write_env_example(target: Path) -> None:
    (target / ".env.example").write_text(
        "NEO4J_URI=bolt://localhost:7687\n"
        "NEO4J_DATABASE=neo4j\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=ontology-password\n"
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
        "data/normalized/\n"
        "data/processed/\n"
        "*.sqlite\n"
        "*.sqlite3\n"
        "*.log\n\n"
        "# Rebuildable local demo portal\n"
        "portal/\n\n"
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
        "      - \"7474:7474\"\n"
        "      - \"7687:7687\"\n"
        "    environment:\n"
        "      NEO4J_AUTH: neo4j/ontology-password\n"
        "  ontology-agent-api:\n"
        "    image: python:3.12-slim\n"
        "    working_dir: /workspace\n"
        "    volumes:\n"
        "      - .:/workspace\n"
        "    command: ontology-agent serve --host 0.0.0.0 --port 8080\n"
        "    ports:\n"
        "      - \"8080:8080\"\n",
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
    (target / "ontology" / "mappings.yaml").write_text(
        "entity_types:\n"
        "  - Person\n"
        "  - Organization\n"
        "  - Technology\n"
        "  - Concept\n"
        "  - System\n"
        "  - Module\n"
        "  - Package\n"
        "  - File\n"
        "  - Class\n"
        "  - Function\n"
        "  - APIEndpoint\n"
        "  - DataModel\n"
        "  - Database\n"
        "  - DataStore\n"
        "  - Queue\n"
        "  - ExternalService\n"
        "  - DeploymentUnit\n"
        "  - Environment\n"
        "  - Config\n"
        "  - SecretRef\n"
        "  - Workflow\n"
        "  - UserRole\n"
        "  - Decision\n"
        "  - Requirement\n"
        "  - Issue\n"
        "  - Task\n"
        "  - BusinessEntity\n"
        "predicates:\n"
        "  - mentions\n"
        "  - related_to\n"
        "  - blocks\n"
        "  - requires\n"
        "  - decides\n"
        "  - uses\n"
        "  - implements\n"
        "  - supports\n"
        "  - depends_on\n"
        "  - generates\n"
        "  - stores\n"
        "  - classifies\n"
        "  - documents\n"
        "  - configures\n"
        "  - runs_on\n"
        "  - exports\n"
        "  - owned_by\n"
        "  - manages\n"
        "  - enriches\n"
        "  - discovers\n"
        "  - creates\n"
        "  - validates\n"
        "  - syncs\n"
        "  - contains\n"
        "  - produces\n"
        "  - reads_from\n"
        "  - writes_to\n"
        "  - calls\n"
        "  - imports\n"
        "  - imports_from\n"
        "  - defines\n"
        "  - exposes\n"
        "  - handles\n"
        "  - deploys_to\n"
        "  - evidences\n"
        "  - part_of\n"
        "  - references\n"
        "  - inherits\n"
        "  - rationale_for\n"
        "  - shares_data_with\n"
        "  - method\n"
        "  - reports_to\n"
        "  - member_of\n"
        "  - has_role\n"
        "  - has_skill\n"
        "  - located_in\n"
        "  - filed_by\n"
        "  - covered_by\n"
        "  - has_document\n"
        "  - evaluated_by\n"
        "  - triggered_rule\n"
        "  - resulted_in\n"
        "  - handled_by\n"
        "  - match_in_league\n"
        "  - team_played_match\n"
        "  - player_played_match\n"
        "  - player_played_for\n"
        "  - team_in_league\n"
        "  - model_artifact_describes\n"
        "  - model_artifact_generated\n"
        "  - prediction_for_match\n"
        "  - prediction_uses_market\n"
        "  - bet_on_match\n"
        "  - bet_uses_market\n",
        encoding="utf-8",
    )
    (target / "ontology" / "datasets").mkdir(parents=True, exist_ok=True)


def _write_makefile(target: Path) -> None:
    (target / "Makefile").write_text(
        "SHELL := /bin/bash\n"
        "ONTOLOGY_AGENT ?= ontology-agent\n"
        "-include .env\n"
        "export\n\n"
        ".PHONY: all check publish publish-prune portal portal-neo4j view demo "
        "demo-dry-run reset-neo4j clean-generated "
        "ci docs doctor ingest graphify dry-run graph wiki sync-dry-run full-stack "
        "sync-neo4j serve smoke-dry-run data-inspect data-sample "
        "smoke-neo4j test\n\n"
        "check:\n\t$(ONTOLOGY_AGENT) run --dry-run\n\n"
        "publish:\n\t$(ONTOLOGY_AGENT) run --neo4j\n\n"
        "publish-prune:\n\t$(ONTOLOGY_AGENT) run --neo4j --prune stale\n\n"
        "portal:\n\t$(ONTOLOGY_AGENT) portal build --dry-run\n\n"
        "portal-neo4j:\n\t$(ONTOLOGY_AGENT) portal build --neo4j\n\n"
        "view:\n\t$(ONTOLOGY_AGENT) portal serve\n\n"
        "demo:\n\t$(ONTOLOGY_AGENT) demo\n\n"
        "demo-dry-run:\n\t$(ONTOLOGY_AGENT) demo --dry-run\n\n"
        "all:\n\t$(ONTOLOGY_AGENT) full-stack\n\n"
        "reset-neo4j:\n\t$(ONTOLOGY_AGENT) graph reset --yes\n\n"
        "clean-generated:\n\trm -rf data/normalized data/processed wiki portal graphify-out\n\n"
        "ci:\n"
        "\tuv run --extra dev pytest\n"
        "\tuv run --extra dev ruff check .\n"
        "\tuv run --extra dev mypy src/company_ontology_agent\n"
        "\tuv run --extra dev mkdocs build --strict\n"
        "\tuv build\n\n"
        "docs:\n\tuv run --extra dev mkdocs serve\n\n"
        "doctor:\n\t$(ONTOLOGY_AGENT) doctor --strict\n\n"
        "ingest:\n\t$(ONTOLOGY_AGENT) ingest ./data/raw\n\n"
        "data-inspect:\n\t$(ONTOLOGY_AGENT) data inspect\n\n"
        "data-sample:\n\t$(ONTOLOGY_AGENT) data sample-template data_reply\n\n"
        "graphify:\n"
        "\trm -f graphify-out/GRAPH_REPORT.md\n"
        "\t$(ONTOLOGY_AGENT) graphify run\n\n"
        "dry-run:\n\t$(ONTOLOGY_AGENT) run --dry-run\n\n"
        "graph:\n"
        "\t$(ONTOLOGY_AGENT) graph bootstrap\n"
        "\t$(ONTOLOGY_AGENT) build-graph\n\n"
        "verify-visuals:\n\t$(ONTOLOGY_AGENT) graph verify-visuals --neo4j\n\n"
        "wiki:\n\t$(ONTOLOGY_AGENT) export-wiki --neo4j\n\n"
        "sync-dry-run:\n\t$(ONTOLOGY_AGENT) run --dry-run\n\n"
        "sync-neo4j:\n\t$(ONTOLOGY_AGENT) run --neo4j\n\n"
        "full-stack:\n\t$(ONTOLOGY_AGENT) full-stack\n\n"
        "serve:\n\t$(ONTOLOGY_AGENT) serve\n\n"
        "smoke-dry-run:\n\tpython scripts/smoke_e2e.py --dry-run\n\n"
        "smoke-neo4j:\n\tpython scripts/smoke_e2e.py\n\n"
        "test:\n\tpytest\n",
        encoding="utf-8",
    )


def _write_scripts(target: Path) -> None:
    scripts = {
        "bootstrap_neo4j.py": (
            "from pathlib import Path\n"
            "from company_ontology_agent.config.project_config import load_project_config\n"
            "from company_ontology_agent.workflows.build_graph import repository_for\n\n"
            "root = Path.cwd()\n"
            "config = load_project_config(root)\n"
            "repo = repository_for(root, config, dry_run=False)\n"
            "repo.bootstrap()\n"
            "print('Neo4j bootstrap complete')\n"
        ),
        "run_graphify.py": (
            "from pathlib import Path\n"
            "from company_ontology_agent.config.project_config import load_project_config\n"
            "from company_ontology_agent.extraction.graphify_adapter import GraphifyExtractor\n\n"
            "root = Path.cwd()\n"
            "config = load_project_config(root)\n"
            "extractor = GraphifyExtractor.from_config(root, config)\n"
            "result = extractor.run(root / config.graphify.input_path, config.project_slug)\n"
            "print('\\n'.join(result.summary_lines()))\n"
        ),
        "export_wiki.py": (
            "from pathlib import Path\n"
            "from company_ontology_agent.config.project_config import load_project_config\n"
            "from company_ontology_agent.wiki.exporter import WikiExporter\n"
            "from company_ontology_agent.workflows.build_graph import repository_for\n\n"
            "root = Path.cwd()\n"
            "config = load_project_config(root)\n"
            "graph = repository_for(root, config, dry_run=True).read_graph(config.project_slug)\n"
            "files = WikiExporter().export(\n"
            "    graph,\n"
            "    root / config.wiki.output_path,\n"
            "    display_name=config.project_name,\n"
            ")\n"
            "print(f'Exported {len(files)} wiki files')\n"
        ),
        "smoke_e2e.py": (
            "import argparse\n"
            "from pathlib import Path\n"
            "from company_ontology_agent.ingestion.folder import ingest_folder\n"
            "from company_ontology_agent.workflows.build_graph import build_graph, repository_for\n"
            "from company_ontology_agent.config.project_config import load_project_config\n"
            "from company_ontology_agent.wiki.exporter import WikiExporter\n\n"
            "parser = argparse.ArgumentParser()\n"
            "parser.add_argument('--dry-run', action='store_true')\n"
            "args = parser.parse_args()\n"
            "root = Path.cwd()\n"
            "config = load_project_config(root)\n"
            "ingest_folder(root / 'data/raw', root)\n"
            "result = build_graph(root, dry_run=args.dry_run)\n"
            "repo = repository_for(root, config, dry_run=args.dry_run)\n"
            "graph = repo.read_graph(config.project_slug)\n"
            "files = WikiExporter().export(\n"
            "    graph,\n"
            "    root / config.wiki.output_path,\n"
            "    display_name=config.project_name,\n"
            ")\n"
            "print(\n"
            "    f'entities={len(result.graph.entities)} '\n"
            "    f'assertions={len(result.graph.assertions)} '\n"
            "    f'wiki_files={len(files)}'\n"
            ")\n"
        ),
    }
    for name, content in scripts.items():
        (target / "scripts" / name).write_text(content, encoding="utf-8")


def _write_readme(
    target: Path, project_slug: str, with_docker: bool, with_markdown_wiki: bool
) -> None:
    docker_step = "docker compose up -d\n" if with_docker else ""
    wiki_note = "Markdown wiki output is enabled.\n" if with_markdown_wiki else ""
    (target / "README.md").write_text(
        f"# {project_slug}\n\n"
        f"{wiki_note}\n"
        "## Daily Commands\n\n"
        "```bash\n"
        f"{docker_step}"
        "cp .env.example .env\n"
        "make doctor\n"
        "make check\n"
        "make portal\n"
        "make view\n"
        "make demo-dry-run\n"
        "make publish\n"
        "make demo\n"
        "make all\n"
        "make wiki\n"
        "```\n"
        "\n"
        "The `wiki/` folder is project-local and intended to be committed. "
        "`data/normalized/`, `data/processed/`, and Graphify internals are rebuildable "
        "and ignored by git. Use `make portal` or `make view` for local graph viewing "
        "without Neo4j. `make publish` is additive and idempotent in Neo4j; use "
        "`make reset-neo4j` only for a clean local rebuild. In Neo4j Explore, click "
        "`DemoNode` for the no-query view or use `graph/explore.cypher` query 1 for "
        "the curated manager demo graph.\n",
        encoding="utf-8",
    )
