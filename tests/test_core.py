from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from company_ontology_agent.cli.main import _strict_required_checks_pass, app
from company_ontology_agent.config.project_config import load_project_config
from company_ontology_agent.extraction.graphify_adapter import render_graphify_report
from company_ontology_agent.extraction.llm_structured_extractor import LLMStructuredExtractor
from company_ontology_agent.graph.cypher import CONSTRAINTS
from company_ontology_agent.ingestion.normalizer import read_normalized_jsonl
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.utils.ids import stable_id


def _graphify_runnable() -> bool:
    """True only if the external graphify tool is present AND actually executes.

    Guards the full-pipeline integration test so ``make test`` stays green where
    graphify isn't installed (or a console-script has a stale shebang).
    """
    exe = shutil.which("graphify")
    if not exe:
        return False
    try:
        subprocess.run([exe, "--help"], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


_GRAPHIFY_RUNNABLE = _graphify_runnable()


def test_stable_id_is_replayable() -> None:
    assert stable_id("entity", "Neo4j") == stable_id("entity", "Neo4j")


def test_constraints_include_assertion_model() -> None:
    assert "assertion_id" in CONSTRAINTS
    assert "entity_id" in CONSTRAINTS


def test_repo_infrastructure_docs_are_showcase_ready() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    pre_commit = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    ci = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "```mermaid" in readme
    assert "MkDocs builds the documentation into `site/`" in readme
    assert "gh-pages" in readme
    assert "uv run --extra dev ruff check ." in pre_commit
    assert "uv run --extra dev mypy src/company_ontology_agent" in pre_commit
    assert "uv run --extra dev pytest" in pre_commit
    assert "uv run --extra dev mypy src/company_ontology_agent" in ci


@pytest.mark.skipif(
    not _GRAPHIFY_RUNNABLE, reason="graphify tool not installed/runnable in this environment"
)
def test_cli_init_ingest_run_and_wiki(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["init", "acme-poc", "--with-docker", "--with-markdown-wiki"],
    )
    assert result.exit_code == 0, result.output
    project = Path("acme-poc")
    assert (project / "project.yaml").exists()
    assert (project / "docker-compose.yml").exists()
    assert (project / ".gitignore").exists()

    gitignore = (project / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "data/raw/" in gitignore
    assert "data/normalized/" in gitignore
    assert "data/processed/" in gitignore
    assert "portal/" in gitignore
    assert "graphify-out/**" in gitignore
    assert "!wiki/**/*.md" in gitignore

    makefile = (project / "Makefile").read_text(encoding="utf-8")
    assert "-include .env" in makefile
    assert "check:" in makefile
    assert "publish:" in makefile
    assert "publish-prune:" in makefile
    assert "data-inspect:" in makefile
    assert "data-sample:" in makefile
    assert "all:" in makefile
    assert "reset-neo4j:" in makefile
    assert "clean-generated:" in makefile
    assert "dry-run:" in makefile
    assert "sync-neo4j:" in makefile
    assert "full-stack:" in makefile
    assert "portal:" in makefile
    assert "view:" in makefile
    assert "verify-visuals:" in makefile
    assert "demo:" in makefile
    assert "rag-index:" in makefile
    assert "rag-evaluate:" in makefile
    assert (project / "rag" / "questions.yaml").exists()

    config = load_project_config(project)
    assert config.project_slug == "acme-poc"

    raw = project / "data" / "raw" / "meeting.md"
    raw.write_text(
        "Decision: Use Neo4j as canonical graph.\nGraphify helps bootstrap extraction.\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(project)
    ingest = runner.invoke(app, ["ingest", "./data/raw"], catch_exceptions=False)
    assert ingest.exit_code == 0, ingest.output
    normalized = list(Path("data/normalized").glob("*.jsonl"))
    assert normalized
    assert read_normalized_jsonl(normalized[0])

    build = runner.invoke(app, ["build-graph", "--dry-run"], catch_exceptions=False)
    assert build.exit_code == 0, build.output
    assert Path("data/processed/graph.json").exists()
    graph_text = Path("data/processed/graph.json").read_text(encoding="utf-8")

    wiki = runner.invoke(app, ["export-wiki"], catch_exceptions=False)
    assert wiki.exit_code == 0, wiki.output
    assert Path("wiki/index.md").exists()
    wiki_text = Path("wiki/index.md").read_text(encoding="utf-8")

    run = runner.invoke(app, ["run", "--dry-run"], catch_exceptions=False)
    assert run.exit_code == 0, run.output
    assert "[1/4] Checking project" in run.output
    assert "[4/4] Building graph" in run.output
    # Re-running the pipeline is idempotent: graph and wiki stay byte-stable.
    assert Path("data/processed/graph.json").read_text(encoding="utf-8") == graph_text
    assert Path("wiki/index.md").read_text(encoding="utf-8") == wiki_text

    help_result = runner.invoke(app, ["--help"], catch_exceptions=False)
    assert help_result.exit_code == 0, help_result.output
    assert "full-stack" in help_result.output


def test_graph_verify_visuals_fails_without_curated_graph(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["init", "acme-poc"]).exit_code == 0
    monkeypatch.chdir(tmp_path / "acme-poc")

    result = runner.invoke(app, ["graph", "verify-visuals", "--dry-run"])

    assert result.exit_code == 1
    assert "No usable curated visual graph found" in result.output


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
            "--with-markdown-wiki",
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
    }

    assert _strict_required_checks_pass(checks)


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


def test_local_fallback_filters_random_tokens(tmp_path: Path) -> None:
    normalized = tmp_path / "normalized.jsonl"
    normalized.write_text(
        '{"id":"r1","source_id":"s1","source_path":"docs/deploy.md",'
        '"source_type":"markdown","title":"Deploy",'
        '"text":"FastAPI runs with Docker and PostgreSQL. '
        'Ignore AAB9hiomQs5DXWcRB1rqsxGUstbRroFOPPVAomNk.",'
        '"ordinal":0,"sha256":"abc"}\n',
        encoding="utf-8",
    )

    graph = LLMStructuredExtractor().extract(normalized, "acme-poc")
    names = {entity.name for entity in graph.entities}

    assert {"FastAPI", "Docker", "PostgreSQL"}.issubset(names)
    assert "AAB9hiomQs5DXWcRB1rqsxGUstbRroFOPPVAomNk" not in names
    assert graph.assertions
