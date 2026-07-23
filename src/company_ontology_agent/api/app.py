from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Any, cast

from pydantic import BaseModel, Field, field_validator

from company_ontology_agent.retrieval.runtime import (
    GraphLayer,
    ProjectRagRuntime,
    create_rag_runtime,
    get_rag_status,
)

logger = logging.getLogger(__name__)


class RagQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must not be blank.")
        return value


class EntitySearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=200)
    layer: GraphLayer = "all"
    limit: int = Field(default=25, ge=1, le=50)


def create_app(
    project_root: Path,
    runtime: ProjectRagRuntime | None = None,
    *,
    allow_text2cypher: bool = False,
) -> Any:
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, RedirectResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Portal GraphRAG serving requires company-ontology-agent[rag].") from exc

    @asynccontextmanager
    async def lifespan(app: Any) -> Any:
        yield
        active = app.state.rag_runtime
        if app.state.owns_rag_runtime and active is not None:
            active.close()

    app = FastAPI(
        title="Ontology Atlas",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.rag_runtime = runtime
    app.state.owns_rag_runtime = runtime is None
    runtime_lock = Lock()

    def active_runtime() -> ProjectRagRuntime:
        if app.state.rag_runtime is None:
            with runtime_lock:
                if app.state.rag_runtime is None:
                    app.state.rag_runtime = (
                        create_rag_runtime(project_root, allow_text2cypher=True)
                        if allow_text2cypher
                        else create_rag_runtime(project_root)
                    )
        return cast(ProjectRagRuntime, app.state.rag_runtime)

    @app.get("/api/rag/status")
    def rag_status() -> dict[str, object]:
        try:
            return active_runtime().status().model_dump()
        except Exception:
            status = get_rag_status(project_root)
            if not status.ready:
                status.message = "GraphRAG is unavailable. Check the server logs."
            return status.model_dump()

    @app.post("/api/rag/query")
    def rag_query(request: RagQueryRequest) -> dict[str, object]:
        try:
            return active_runtime().ask(request.question).model_dump(mode="json")
        except Exception as exc:
            status_code = 504 if _is_timeout_error(exc) else 503
            trace_id = uuid.uuid4().hex[:16]
            logger.exception("GraphRAG query failed trace_id=%s", trace_id)
            message = (
                "GraphRAG query timed out."
                if status_code == 504
                else "GraphRAG is unavailable."
            )
            raise HTTPException(
                status_code=status_code,
                detail={"message": message, "trace_id": trace_id},
            ) from exc

    @app.get("/api/entities/search")
    def entity_search(q: str, layer: str = "all", limit: int = 25) -> dict[str, object]:
        try:
            request = EntitySearchQuery(q=q.strip(), layer=layer, limit=limit)
            return {
                "results": active_runtime().search_entities(
                    request.q, layer=request.layer, limit=request.limit
                )
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            trace_id = uuid.uuid4().hex[:16]
            logger.exception("Entity search failed trace_id=%s", trace_id)
            raise HTTPException(
                status_code=503,
                detail={"message": "Entity search is unavailable.", "trace_id": trace_id},
            ) from exc

    @app.get("/api/sources")
    def sources() -> dict[str, object]:
        try:
            return {"sources": active_runtime().list_sources()}
        except Exception as exc:
            trace_id = uuid.uuid4().hex[:16]
            logger.exception("Source listing failed trace_id=%s", trace_id)
            raise HTTPException(
                status_code=503,
                detail={"message": "Source browsing is unavailable.", "trace_id": trace_id},
            ) from exc

    @app.get("/api/sources/{source_id}")
    def source_detail(source_id: str) -> dict[str, object]:
        try:
            chunks = active_runtime().source_chunks(source_id)
        except Exception as exc:
            trace_id = uuid.uuid4().hex[:16]
            logger.exception("Source detail failed trace_id=%s", trace_id)
            raise HTTPException(
                status_code=503,
                detail={"message": "Source browsing is unavailable.", "trace_id": trace_id},
            ) from exc
        if not chunks:
            raise HTTPException(status_code=404, detail="Source not found or has no text.")
        return {"chunks": chunks}

    @app.get("/", include_in_schema=False)
    def root() -> object:
        return RedirectResponse("/portal/index.html")

    @app.get("/graphify-out/{filename}", include_in_schema=False)
    def graphify_diagnostic(filename: str) -> object:
        if filename not in {"graph.html", "graph.raw.html", "GRAPH_TREE.html", "GRAPH_REPORT.md"}:
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


def _is_timeout_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".casefold()
    return isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text
