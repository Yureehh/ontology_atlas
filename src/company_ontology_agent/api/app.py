from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from company_ontology_agent.retrieval.runtime import ask_project, get_rag_status


class RagQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank.")
        return value


def create_app(project_root: Path) -> Any:
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, RedirectResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Portal GraphRAG serving requires company-ontology-agent[rag].") from exc

    app = FastAPI(title="Ontology Atlas", docs_url=None, redoc_url=None)

    @app.get("/api/rag/status")
    def rag_status() -> dict[str, object]:
        return get_rag_status(project_root).model_dump()

    @app.post("/api/rag/query")
    def rag_query(request: RagQueryRequest) -> dict[str, object]:
        try:
            return ask_project(project_root, request.question).model_dump(mode="json")
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/", include_in_schema=False)
    def root() -> object:
        return RedirectResponse("/portal/index.html")

    @app.get("/graphify-out/{filename}", include_in_schema=False)
    def graphify_diagnostic(filename: str) -> object:
        if filename not in {"GRAPH_TREE.html", "GRAPH_REPORT.md"}:
            raise HTTPException(status_code=404, detail="Not found")
        target = project_root / "graphify-out" / filename
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(target)

    for route, directory in (("/portal", "portal"), ("/wiki", "wiki")):
        path = project_root / directory
        if path.is_dir():
            app.mount(route, StaticFiles(directory=path, html=True), name=directory)
    return app
