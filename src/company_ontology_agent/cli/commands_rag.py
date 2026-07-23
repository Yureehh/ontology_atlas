from __future__ import annotations

import typer

from company_ontology_agent.config.project_config import find_project_root
from company_ontology_agent.retrieval.evaluation import evaluate_questions, load_questions
from company_ontology_agent.retrieval.runtime import (
    ask_project,
    create_rag_runtime,
    get_rag_status,
    index_project,
)

rag_app = typer.Typer(help="Index and query the Neo4j GraphRAG knowledge layer.")


@rag_app.command("index")
def rag_index() -> None:
    result = index_project(find_project_root())
    typer.echo(
        f"GraphRAG index ready: total={result.total}, indexed={result.indexed}, "
        f"unchanged={result.unchanged}, deleted={result.deleted}."
    )


@rag_app.command("ask")
def rag_ask(question: str) -> None:
    response = ask_project(find_project_root(), question)
    typer.echo(response.model_dump_json(indent=2))


@rag_app.command("status")
def rag_status() -> None:
    typer.echo(get_rag_status(find_project_root()).model_dump_json(indent=2))


@rag_app.command("evaluate")
def rag_evaluate() -> None:
    root = find_project_root()
    questions = load_questions(root / "rag" / "questions.yaml")
    runtime = create_rag_runtime(root)
    try:
        report = evaluate_questions(questions, runtime.ask, project_root=root)
    finally:
        runtime.close()
    output = root / "rag" / "evaluation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(report.model_dump_json(indent=2))
    typer.echo(f"Saved evaluation: {output}")
    if report.passed != report.total:
        raise typer.Exit(code=1)
