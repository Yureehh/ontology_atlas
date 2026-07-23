from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import company_ontology_agent.cli.main as cli_main
from company_ontology_agent.cli.main import _strict_required_checks_pass, app
from company_ontology_agent.config.project_config import load_project_config, write_project_config
from company_ontology_agent.config.templates import scaffold_project
from company_ontology_agent.extraction.graphify_report import render_graphify_report
from company_ontology_agent.graph.cypher import CONSTRAINTS
from company_ontology_agent.graph.models import Entity, EntityType, ExtractedGraph
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.utils.ids import stable_id


def test_stable_id_is_replayable() -> None:
    assert stable_id("entity", "Neo4j") == stable_id("entity", "Neo4j")


def test_constraints_include_assertion_model() -> None:
    assert "assertion_id" in CONSTRAINTS
    assert "entity_id" in CONSTRAINTS


def test_entity_metadata_supports_recursive_json_without_serializer_warnings() -> None:
    entity = Entity(
        id="team",
        type=EntityType.business_entity,
        name="Team Liquid",
        normalized_name="team liquid",
        metadata={
            "datasets": ["matches", "team_league_mapping"],
            "dataset_sources": {"matches": ["models/matches.parquet"]},
        },
    )

    assert "dataset_sources" in entity.model_dump_json(warnings="error")


def test_project_config_rejects_obsolete_keys_with_migration_hint(tmp_path: Path) -> None:
    (tmp_path / "project.yaml").write_text(
        "project_slug: portable\nproject_name: Portable\nlocal_fallback_enabled: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unsupported project.yaml settings.*local_fallback"):
        load_project_config(tmp_path)


def test_generated_project_keeps_one_runnable_cli_surface(tmp_path: Path) -> None:
    project = scaffold_project(
        tmp_path / "client-atlas",
        "client-atlas",
        with_docker=True,
        force=False,
    )

    compose = (project / "docker-compose.yml").read_text(encoding="utf-8")
    makefile = (project / "Makefile").read_text(encoding="utf-8")
    project_yaml = (project / "project.yaml").read_text(encoding="utf-8")

    assert "ontology-agent-api" not in compose
    assert "ontology-agent serve" not in compose
    assert "127.0.0.1:7687:7687" in compose
    assert "${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-ontology-password}" in compose
    assert "$(ONTOLOGY_AGENT) launch" in makefile
    assert "start: neo4j" in makefile
    assert "rag/index-status.json" in makefile
    assert "refresh: neo4j" in makefile
    assert "Neo4j already available on 127.0.0.1:7687" in makefile
    assert "docker compose up -d neo4j" in makefile
    assert "$(ONTOLOGY_AGENT) launch --no-serve" in makefile
    assert "stop:" in makefile
    assert "docker compose stop neo4j" in makefile
    assert "\nserve:" not in makefile
    assert "\nci:" not in makefile
    generated_readme = (project / "README.md").read_text(encoding="utf-8")
    for removed_target in ["make portal", "make view", "make publish", "make reset-neo4j"]:
        assert removed_target not in generated_readme
    assert not (project / "scripts").exists()
    assert not (project / "tests").exists()
    assert not (project / "logs").exists()
    assert not (project / "NEO4J_EXPLORE_GUIDE.md").exists()
    assert not (project / "graph" / "bootstrap.cypher").exists()
    for unused_section in ["runtime:", "sync:", "environment:", "extraction_mode:"]:
        assert unused_section not in project_yaml


def test_generated_project_without_docker_keeps_simple_native_workflow(tmp_path: Path) -> None:
    project = scaffold_project(
        tmp_path / "client-atlas",
        "client-atlas",
        with_docker=False,
        force=False,
    )

    makefile = (project / "Makefile").read_text(encoding="utf-8")

    assert "start: neo4j" in makefile
    assert "rag/index-status.json" in makefile
    assert "$(ONTOLOGY_AGENT) launch --no-serve" in makefile
    assert "docker compose" not in makefile


def test_repo_infrastructure_docs_are_showcase_ready() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    pre_commit = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "```mermaid" in readme
    assert "MkDocs builds the documentation into `site/`" in readme
    assert "gh-pages" in readme
    assert "uv run --extra dev --extra rag ruff check ." in pre_commit
    assert "uv run --extra dev --extra rag mypy src/company_ontology_agent" in pre_commit
    assert "uv run --extra dev --extra rag pytest" in pre_commit
    assert "uv run --extra dev --extra rag mypy src/company_ontology_agent" in ci


def test_cli_init_run_and_wiki(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init", "acme-poc", "--with-docker"],
    )
    assert result.exit_code == 0, result.output
    project = Path("acme-poc")
    assert (project / "project.yaml").exists()
    assert (project / "docker-compose.yml").exists()
    assert (project / ".gitignore").exists()

    gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "data/raw/" in gitignore
    assert "data/processed/" in gitignore
    assert "portal/" in gitignore
    assert "graphify-out/**" in gitignore
    assert "!wiki/**/*.md" in gitignore

    makefile = (project / "Makefile").read_text(encoding="utf-8")
    assert "-include .env" in makefile
    assert "check:" in makefile
    assert "start:" in makefile
    assert "refresh:" in makefile
    assert "reset:" in makefile
    assert "clean-generated:" in makefile
    assert "evaluate:" in makefile
    assert (project / "rag" / "questions.yaml").exists()

    config = load_project_config(project)
    assert config.project_slug == "acme-poc"
    # This test exercises Atlas pipeline orchestration, not the external Graphify process.
    config.graphify.enabled = False
    write_project_config(config, project / "project.yaml")

    raw = project / "data" / "raw" / "meeting.md"
    raw.write_text(
        "Decision: Use Neo4j as canonical graph.\nGraphify helps bootstrap extraction.\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(project)
    build = runner.invoke(app, ["build-graph", "--dry-run"], catch_exceptions=False)
    assert build.exit_code == 0, build.output
    assert Path("data/processed/graph.json").exists()
    wiki = runner.invoke(app, ["export-wiki"], catch_exceptions=False)
    assert wiki.exit_code == 0, wiki.output
    assert Path("wiki/index.md").exists()
    run = runner.invoke(app, ["run", "--dry-run"], catch_exceptions=False)
    assert run.exit_code == 0, run.output
    assert "[1/3] Checking project" in run.output
    assert "[3/3] Building graph" in run.output
    graph_text = Path("data/processed/graph.json").read_text(encoding="utf-8")
    wiki_text = Path("wiki/index.md").read_text(encoding="utf-8")

    rerun = runner.invoke(app, ["run", "--dry-run"], catch_exceptions=False)
    assert rerun.exit_code == 0, rerun.output
    # Re-running the complete pipeline is idempotent: graph and wiki stay byte-stable.
    assert Path("data/processed/graph.json").read_text(encoding="utf-8") == graph_text
    assert Path("wiki/index.md").read_text(encoding="utf-8") == wiki_text

    help_result = runner.invoke(app, ["--help"], catch_exceptions=False)
    assert help_result.exit_code == 0, help_result.output
    assert "full-stack" not in help_result.output
    assert "ingest" not in help_result.output
    assert "launch" in help_result.output


def test_graph_verify_visuals_fails_without_curated_graph(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "acme-poc")

    result = runner.invoke(app, ["graph", "verify-visuals", "--dry-run"])

    assert result.exit_code == 1
    assert "No usable curated visual graph found" in result.output


def test_portal_rejects_network_exposure_without_explicit_flag() -> None:
    result = CliRunner().invoke(app, ["portal", "serve", "--host", "0.0.0.0"])

    assert result.exit_code != 0
    assert "--allow-network" in result.output


def test_import_raw_avoids_nested_raw_folder(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    source = tmp_path / "export"
    (source / "raw" / "websmith").mkdir(parents=True)
    (source / "raw" / "websmith" / "README.md").write_text("Hello", encoding="utf-8")

    monkeypatch.chdir(tmp_path / "acme-poc")
    result = runner.invoke(app, ["import-raw", str(source)], catch_exceptions=False)

    assert result.exit_code == 0, result.output
    assert Path("data/raw/websmith/README.md").exists()
    assert not Path("data/raw/raw").exists()


def test_import_raw_code_docs_profile_excludes_noisy_files(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    source = tmp_path / "repo"
    (source / "app").mkdir(parents=True)
    (source / "frontend/node_modules/pkg").mkdir(parents=True)
    (source / ".venv/lib").mkdir(parents=True)
    (source / ".uv-cache/sdists-v9").mkdir(parents=True)
    (source / ".pre-commit-cache").mkdir(parents=True)
    (source / "demo.egg-info").mkdir(parents=True)
    (source / ".claude").mkdir(parents=True)
    (source / ".vscode").mkdir(parents=True)
    (source / "saved_reports/images").mkdir(parents=True)
    (source / "app/main.py").write_text("print('ok')\n", encoding="utf-8")
    (source / "README.md").write_text("# Repo\n", encoding="utf-8")
    (source / ".env").write_text("SECRET=yes\n", encoding="utf-8")
    (source / ".claude/settings.local.json").write_text("{}", encoding="utf-8")
    (source / ".vscode/settings.json").write_text("{}", encoding="utf-8")
    (source / "frontend/node_modules/pkg/index.js").write_text("bad\n", encoding="utf-8")
    (source / ".venv/lib/site.py").write_text("bad\n", encoding="utf-8")
    (source / ".uv-cache/sdists-v9/.gitignore").write_text("bad\n", encoding="utf-8")
    (source / ".pre-commit-cache/README").write_text("bad\n", encoding="utf-8")
    (source / "demo.egg-info/SOURCES.txt").write_text("bad\n", encoding="utf-8")
    (source / "saved_reports/images/chart.png").write_bytes(b"bad")

    monkeypatch.chdir(tmp_path / "acme-poc")
    result = runner.invoke(
        app,
        ["import-raw", str(source), "--profile", "code-docs", "--clear"],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert Path("data/raw/app/main.py").exists()
    assert Path("data/raw/README.md").exists()
    assert not Path("data/raw/.env").exists()
    assert not Path("data/raw/.claude/settings.local.json").exists()
    assert not Path("data/raw/.vscode/settings.json").exists()
    assert not Path("data/raw/frontend/node_modules/pkg/index.js").exists()
    assert not Path("data/raw/.venv/lib/site.py").exists()
    assert not Path("data/raw/.uv-cache/sdists-v9/.gitignore").exists()
    assert not Path("data/raw/.pre-commit-cache/README").exists()
    assert not Path("data/raw/demo.egg-info/SOURCES.txt").exists()
    assert not Path("data/raw/saved_reports/images/chart.png").exists()


def test_init_can_target_hidden_project_and_import_source(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    source = tmp_path / "repo"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    target = source / ".ontology-agent"
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app,
        [
            "init",
            "slidesmith-poc",
            "--target",
            str(target),
            "--source",
            str(source),
            "--source-profile",
            "code-docs",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert (target / "project.yaml").exists()
    assert (target / "data/raw/pyproject.toml").exists()
    assert not (target / "data/raw/.ontology-agent/project.yaml").exists()


def test_doctor_reports_without_services(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "acme-poc")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "project.yaml" in result.output


def test_launch_refreshes_in_place_when_atlas_is_already_running(
    tmp_path: Path, monkeypatch
) -> None:
    project = scaffold_project(
        tmp_path / "client-atlas",
        "client-atlas",
        with_docker=False,
        force=False,
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        cli_main,
        "_launch_port_status",
        lambda host, port: ("atlas", "http://127.0.0.1:8765/portal/index.html"),
    )

    rebuilds: list[bool] = []
    monkeypatch.setattr(
        cli_main,
        "_run_pipeline",
        lambda **kwargs: rebuilds.append(True) or ExtractedGraph(project_slug="client-atlas"),
    )
    monkeypatch.setattr(cli_main, "_export_outputs", lambda *args, **kwargs: None)

    result = CliRunner().invoke(app, ["launch"], catch_exceptions=False)

    assert result.exit_code == 0
    assert "already running" in result.output
    assert "Refreshing its graph" in result.output
    assert rebuilds == [True]


def test_launch_fails_before_rebuild_when_port_belongs_to_another_service(
    tmp_path: Path, monkeypatch
) -> None:
    project = scaffold_project(
        tmp_path / "client-atlas",
        "client-atlas",
        with_docker=False,
        force=False,
    )
    monkeypatch.chdir(project)
    monkeypatch.setattr(
        cli_main,
        "_launch_port_status",
        lambda host, port: ("occupied", "http://127.0.0.1:8765/portal/index.html"),
    )

    def unexpected_rebuild(**kwargs) -> None:
        pytest.fail("launch rebuilt the project even though its port was occupied")

    monkeypatch.setattr(cli_main, "_run_pipeline", unexpected_rebuild)

    result = CliRunner().invoke(app, ["launch"], catch_exceptions=False)

    assert result.exit_code == 1
    assert "Port 8765 is already in use" in result.output
    assert "--port 8766" in result.output


def test_doctor_warns_on_nested_raw_folder(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    project = tmp_path / "acme-poc"
    (project / "data/raw/raw").mkdir(parents=True)
    monkeypatch.chdir(project)

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "WARN no nested data/raw/raw" in result.output


def test_doctor_strict_fails_without_neo4j_credentials(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "acme-poc")
    result = runner.invoke(app, ["doctor", "--strict"])
    assert result.exit_code == 1
    assert "neo4j connectivity" in result.output


def test_strict_doctor_allows_rebuildable_warnings() -> None:
    checks = {
        "project.yaml": True,
        ".env": True,
        "ontology core": True,
        "ontology shapes": True,
        "raw sources": True,
        "no nested data/raw/raw": True,
        "graphify report freshness": False,
        "graphify": True,
        "docker compose": False,
        "neo4j credentials": True,
        "llm credentials": True,
        "neo4j connectivity": True,
        "GraphRAG configuration": True,
        "GraphRAG dependencies": True,
    }

    assert _strict_required_checks_pass(checks)
    checks["GraphRAG configuration"] = False
    assert not _strict_required_checks_pass(checks)


def test_graphify_report_is_concise_by_default() -> None:
    report = render_graphify_report(
        ["graphify", "extract", "data/raw"],
        0,
        "[graphify extract] found 0 code, 6 docs, 0 papers, 0 images\n"
        "[graphify extract] wrote graphify-out/graph.json: 6 nodes, 8 edges\n"
        "[graphify extract] tokens: 3,676 in / 833 out, est. cost (~openai): $0.0028\n",
        "",
    )

    assert "Status: succeeded" in report
    assert "Scanned: 0 code, 6 docs, 0 papers, 0 images" in report
    assert "Graph: 6 nodes, 8 edges" in report
    assert "## stdout" not in report
    assert "Exit code: 0" not in report


def test_graphify_failure_report_includes_error() -> None:
    report = render_graphify_report(
        ["graphify", "extract", "data/raw"],
        1,
        "",
        "graph is empty",
        warnings=["Graphify execution failed; see graphify-out/GRAPH_REPORT.md."],
    )

    assert "Status: failed" in report
    assert "## Error" in report
    assert "graph is empty" in report


def test_predicate_normalization_maps_common_aliases() -> None:
    assert normalize_predicate("built-with") == "uses"
    assert normalize_predicate("is_required_for") == "requires"
    assert normalize_predicate("runs on") == "runs_on"
