from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from company_ontology_agent.config.project_config import ProjectConfig
from company_ontology_agent.config.settings import runtime_settings
from company_ontology_agent.graph.models import (
    Assertion,
    Entity,
    EntityType,
    ExtractedGraph,
    Source,
    SourceSpan,
)
from company_ontology_agent.ontology.mappings import normalize_predicate
from company_ontology_agent.utils.hashing import stable_hash
from company_ontology_agent.utils.ids import slugify, stable_id


class ProgressReporter(Protocol):
    def __call__(self, message: str) -> None: ...


@dataclass(frozen=True)
class GraphifyCommand:
    executable: str
    input_path: Path
    output_path: Path
    backend: str
    mode: str
    model: str | None
    no_viz: bool

    def argv(self) -> list[str]:
        args = [
            self.executable,
            "extract",
            str(self.input_path),
            "--backend",
            self.backend,
            "--mode",
            self.mode,
            "--out",
            str(self.output_path.parent),
        ]
        if self.model:
            args.extend(["--model", self.model])
        if self.no_viz:
            # Skip graphify's standalone vis-network graph.html — it runs a physics
            # simulation over the whole graph and freezes low-memory machines. The
            # portal provides the interactive graph (static layout, capped + search).
            args.append("--no-viz")
        return args


@dataclass(frozen=True)
class GraphifyRunResult:
    graph: ExtractedGraph
    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    report_path: Path
    graph_json_path: Path | None = None

    @property
    def warning_count(self) -> int:
        return len(self.graph.warnings)

    def summary_lines(self) -> list[str]:
        status = "completed" if self.exit_code == 0 else "failed"
        lines = [f"Graphify {status}: warnings={self.warning_count}"]
        if stats := _parse_scan_stats(self.stdout):
            lines.append(
                "Scanned: "
                f"{stats['code']} code, {stats['docs']} docs, "
                f"{stats['papers']} papers, {stats['images']} images"
            )
        if stats := _parse_graph_stats(self.stdout):
            lines.append(f"Graphify graph: {stats['nodes']} nodes, {stats['edges']} edges")
        if self.graph_json_path:
            lines.append(f"Graphify output: {self.graph_json_path}")
        return lines


class GraphifyExtractor:
    extractor_name = "graphify"

    def __init__(
        self,
        output_path: Path,
        *,
        backend: str = "openai",
        mode: str = "deep",
        model: str | None = None,
        no_viz: bool = True,
        strict: bool = False,
        timeout_seconds: int | None = None,
        auto_name_communities: bool = True,
        executable: str = "graphify",
    ) -> None:
        self.output_path = output_path
        self.backend = backend
        self.mode = mode
        self.model = model
        self.no_viz = no_viz
        self.strict = strict
        self.timeout_seconds = timeout_seconds
        self.auto_name_communities = auto_name_communities
        self.executable = executable

    @classmethod
    def from_config(cls, project_root: Path, config: ProjectConfig) -> GraphifyExtractor:
        settings = runtime_settings(config)
        return cls(
            project_root / config.graphify.output_path,
            backend=config.graphify.backend,
            mode=config.graphify.mode,
            model=settings.llm_model if config.graphify.backend == "openai" else None,
            no_viz=config.graphify.no_viz,
            strict=config.graphify.strict,
            timeout_seconds=config.graphify.timeout_seconds,
            auto_name_communities=config.graphify.auto_name_communities,
        )

    def extract(self, input_path: Path, project_slug: str) -> ExtractedGraph:
        return self.run(input_path, project_slug).graph

    def cluster(self, project_root: Path) -> subprocess.CompletedProcess[str]:
        executable = resolve_graphify_executable(self.executable)
        if executable is None:
            raise RuntimeError("Graphify executable not found.")
        command = [executable, "cluster-only", str(project_root), "--backend", self.backend]
        if self.model:
            command.extend(["--model", self.model])
        if self.no_viz:
            command.append("--no-viz")
        return subprocess.run(
            command, check=False, capture_output=True, text=True, cwd=project_root
        )

    def tree(
        self, project_root: Path, *, label: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        executable = resolve_graphify_executable(self.executable)
        if executable is None:
            raise RuntimeError("Graphify executable not found.")
        command = [executable, "tree", "--graph", str(self.output_path / "graph.json")]
        if label:
            command.extend(["--label", label])
        return subprocess.run(
            command, check=False, capture_output=True, text=True, cwd=project_root
        )

    def run_auxiliary(
        self, project_root: Path, command_name: str, *args: str
    ) -> subprocess.CompletedProcess[str]:
        executable = resolve_graphify_executable(self.executable)
        if executable is None:
            raise RuntimeError("Graphify executable not found.")
        command = [executable, command_name, *args, "--graph", str(self.output_path / "graph.json")]
        return subprocess.run(
            command, check=False, capture_output=True, text=True, cwd=project_root
        )

    def incremental_update(
        self,
        input_path: Path,
        project_slug: str,
        *,
        force: bool = False,
        progress: ProgressReporter | None = None,
    ) -> GraphifyRunResult:
        """Incrementally refresh the graph via ``graphify update`` (re-extract changed code only).

        This is the cheap progressive path: it reuses Graphify's per-file caches and does NOT
        spend LLM tokens on unchanged files. Returns the same :class:`GraphifyRunResult` shape as
        :meth:`run` so the pipeline can use either interchangeably. Note: ``update`` refreshes
        code/AST; a semantic re-extraction of changed *documents* still requires :meth:`run`.
        """
        self.output_path.mkdir(parents=True, exist_ok=True)
        report = self.output_path / "GRAPH_REPORT.md"
        executable = resolve_graphify_executable(self.executable)
        if executable is None:
            message = "Graphify executable not found; cannot run incremental update."
            report.write_text(f"# Graphify Report\n\n{message}\n", encoding="utf-8")
            if self.strict:
                raise RuntimeError(message)
            return GraphifyRunResult(
                graph=ExtractedGraph(project_slug=project_slug, warnings=[message]),
                command=[self.executable, "update"],
                exit_code=127,
                stdout="",
                stderr=message,
                report_path=report,
            )

        with _graphify_visible_input(input_path) as graphify_input_path:
            argv = [executable, "update", str(graphify_input_path)]
            if force:
                argv.append("--force")
            _report(progress, f"Graphify incremental update (no LLM): input={graphify_input_path}.")
            result = _run_with_heartbeat(
                argv,
                cwd=self.output_path.parent,
                progress=progress,
                heartbeat_seconds=15,
                completion_file=self.output_path / "graph.json",
                completion_grace_seconds=30,
                max_runtime_seconds=self.timeout_seconds,
            )
        return self._finish_run(argv, result, project_slug, report)

    def run(
        self,
        input_path: Path,
        project_slug: str,
        *,
        progress: ProgressReporter | None = None,
    ) -> GraphifyRunResult:
        self.output_path.mkdir(parents=True, exist_ok=True)
        report = self.output_path / "GRAPH_REPORT.md"
        executable = resolve_graphify_executable(self.executable)
        if executable is None:
            message = (
                "Graphify executable not found; skipped Graphify extraction. "
                "Install package dependencies or ensure graphify is on PATH."
            )
            report.write_text(f"# Graphify Report\n\n{message}\n", encoding="utf-8")
            if self.strict:
                raise RuntimeError(message)
            graph = ExtractedGraph(project_slug=project_slug, warnings=[message])
            return GraphifyRunResult(
                graph=graph,
                command=[self.executable],
                exit_code=127,
                stdout="",
                stderr=message,
                report_path=report,
            )

        with _graphify_visible_input(input_path) as graphify_input_path:
            command = GraphifyCommand(
                executable=executable,
                input_path=graphify_input_path,
                output_path=self.output_path,
                backend=self.backend,
                mode=self.mode,
                model=self.model,
                no_viz=self.no_viz,
            )
            _report(
                progress,
                "Starting Graphify: "
                f"backend={self.backend}, mode={self.mode}, "
                f"input={graphify_input_path}, output={self.output_path}.",
            )
            result = _run_with_heartbeat(
                command.argv(),
                cwd=self.output_path.parent,
                progress=progress,
                heartbeat_seconds=15,
                completion_file=self.output_path / "graph.json",
                completion_grace_seconds=90,
                max_runtime_seconds=self.timeout_seconds,
            )
        return self._finish_run(command.argv(), result, project_slug, report)

    def _finish_run(
        self,
        argv: list[str],
        result: subprocess.CompletedProcess[str],
        project_slug: str,
        report: Path,
    ) -> GraphifyRunResult:
        """Parse graphify-out/graph.json into an ExtractedGraph and write the report.

        Shared by :meth:`run` and :meth:`update` so both produce an identical result shape.
        """
        graph_json = self.output_path / "graph.json"
        graph_json_path = graph_json if graph_json.exists() else None
        if graph_json.exists():
            graph = parse_graphify_graph(graph_json, project_slug)
            if self.auto_name_communities:
                graph = apply_community_names(graph, self.output_path)
        else:
            graph = ExtractedGraph(
                project_slug=project_slug,
                warnings=["Graphify finished but graphify-out/graph.json was not found."],
            )
        warnings = list(graph.warnings)
        if result.returncode != 0:
            warnings = ["Graphify execution failed; see graphify-out/GRAPH_REPORT.md.", *warnings]
            graph.warnings = warnings
        report.write_text(
            render_graphify_report(
                argv, result.returncode, result.stdout, result.stderr, warnings=warnings
            ),
            encoding="utf-8",
        )
        if result.returncode != 0 and self.strict:
            raise RuntimeError("Graphify execution failed; see graphify-out/GRAPH_REPORT.md.")
        return GraphifyRunResult(
            graph=graph,
            command=argv,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            report_path=report,
            graph_json_path=graph_json_path,
        )


def resolve_graphify_executable(executable: str = "graphify") -> str | None:
    if found := shutil.which(executable):
        return found
    for scripts_dir in (Path(sys.executable).parent, Path(sys.prefix) / "bin"):
        candidate = scripts_dir / executable
        if candidate.exists():
            return str(candidate)
    return None


def _terminate_with_note(
    process: subprocess.Popen[str], command: list[str], note: str
) -> subprocess.CompletedProcess[str]:
    """Terminate a graphify subprocess, drain its output, and return a 124 result + note."""
    process.terminate()
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    stderr = (stderr or "").rstrip()
    if stderr:
        stderr += "\n"
    stderr += note
    return subprocess.CompletedProcess(command, 124, stdout, stderr)


def _run_with_heartbeat(
    command: list[str],
    *,
    cwd: Path,
    progress: ProgressReporter | None,
    heartbeat_seconds: int,
    completion_file: Path | None = None,
    completion_grace_seconds: int = 90,
    max_runtime_seconds: int | None = None,
) -> subprocess.CompletedProcess[str]:
    started = time.monotonic()
    started_wall = time.time()
    stable_since: float | None = None
    last_signature: tuple[int, int] | None = None
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _report(progress, f"Graphify process started with pid={process.pid}.")
    while process.poll() is None:
        time.sleep(heartbeat_seconds)
        elapsed = int(time.monotonic() - started)
        _report(progress, f"Graphify still running after {elapsed}s.")
        if max_runtime_seconds is not None and elapsed >= max_runtime_seconds:
            _report(
                progress,
                f"Graphify exceeded timeout of {max_runtime_seconds}s; terminating process.",
            )
            return _terminate_with_note(
                process,
                command,
                f"Graphify process exceeded timeout of {max_runtime_seconds}s.",
            )
        if completion_file is None or not completion_file.exists():
            continue
        stat = completion_file.stat()
        if stat.st_mtime < started_wall:
            # Stale artifact from a previous run — it would read as "stable" immediately
            # and get a healthy extraction killed. Only a file written by THIS run counts.
            continue
        signature = (stat.st_size, stat.st_mtime_ns)
        now = time.monotonic()
        if signature != last_signature:
            last_signature = signature
            stable_since = now
            continue
        if stable_since is not None and now - stable_since >= completion_grace_seconds:
            _report(
                progress,
                "Graphify graph.json is stable; terminating lingering process "
                "and continuing from the artifact.",
            )
            return _terminate_with_note(
                process,
                command,
                "Graphify process was terminated after graph.json became stable.",
            )

    stdout, stderr = process.communicate()
    elapsed = int(time.monotonic() - started)
    _report(progress, f"Graphify process finished in {elapsed}s with exit={process.returncode}.")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _report(progress: ProgressReporter | None, message: str) -> None:
    if progress is not None:
        progress(message)


@contextmanager
def _graphify_visible_input(input_path: Path) -> Iterator[Path]:
    resolved = input_path.resolve()
    if not _has_hidden_component(resolved):
        yield resolved
        return

    with tempfile.TemporaryDirectory(prefix="ontology-agent-graphify-") as temp_dir:
        mirror = Path(temp_dir) / resolved.name
        if resolved.is_dir():
            shutil.copytree(resolved, mirror)
        else:
            mirror.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, mirror)
        yield mirror


def _has_hidden_component(path: Path) -> bool:
    return any(part.startswith(".") and part not in {".", ".."} for part in path.parts)


def parse_graphify_graph(path: Path, project_slug: str) -> ExtractedGraph:
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_nodes = _extract_collection(data, "nodes")
    raw_edges = _extract_collection(data, "edges") or _extract_collection(data, "links")

    entities_by_raw_id: dict[str, Entity] = {}
    graphify_source = Source(
        id=stable_id("source", "graphify", str(path)),
        path=str(path),
        source_type="graphify_json",
        sha256=stable_hash(path.read_text(encoding="utf-8")),
        title="Graphify graph.json",
    )

    spans: list[SourceSpan] = []
    for raw_node in raw_nodes:
        node = _as_dict(raw_node)
        raw_id = str(node.get("id") or node.get("key") or node.get("name") or node.get("label"))
        name = str(node.get("name") or node.get("label") or node.get("title") or raw_id)
        raw_type = node.get("type") or node.get("kind") or node.get("category")
        raw_type = raw_type or _graphify_node_type(node, name)
        entity_type = _entity_type(str(raw_type))
        normalized = slugify(name).replace("-", " ")
        entities_by_raw_id[raw_id] = Entity(
            id=stable_id("entity", normalized, entity_type.value),
            type=entity_type,
            name=name,
            normalized_name=normalized,
            aliases=_string_list(node.get("aliases")),
            graphify_id=raw_id,
            source_path=_string_value(
                node.get("path")
                or node.get("file")
                or node.get("filepath")
                or node.get("source")
                or node.get("source_file")
            ),
            community=_string_value(
                node.get("community")
                or node.get("cluster")
                or node.get("group")
                or node.get("community_name")
            ),
            extraction_source=_graphify_extraction_source(node),
            confidence_tier="extracted",
            description=_string_value(
                node.get("description") or node.get("summary") or node.get("doc")
            ),
            metadata=_metadata(node),
        )

    assertions: list[Assertion] = []
    for index, raw_edge in enumerate(raw_edges):
        edge = _as_dict(raw_edge)
        source_raw = str(edge.get("source") or edge.get("from") or edge.get("src") or "")
        target_raw = str(edge.get("target") or edge.get("to") or edge.get("dst") or "")
        source = entities_by_raw_id.get(source_raw)
        target = entities_by_raw_id.get(target_raw)
        if source is None or target is None:
            continue
        predicate = normalize_predicate(
            slugify(
                str(
                    edge.get("predicate")
                    or edge.get("relationship")
                    or edge.get("relation")
                    or edge.get("type")
                    or edge.get("label")
                    or "related_to"
                )
            ).replace("-", "_")
        )
        confidence = _confidence(edge.get("confidence_score", edge.get("confidence")))
        confidence_tier = _confidence_tier(edge)
        source_path = _string_value(
            edge.get("path") or edge.get("file") or edge.get("filepath") or edge.get("source_path")
        )
        evidence_id = stable_id("span", "graphify", path.name, index, source_path or "")
        evidence_text = str(
            edge.get("evidence")
            or edge.get("context")
            or edge.get("reason")
            or edge.get("label")
            or predicate
        )
        spans.append(
            SourceSpan(
                id=evidence_id,
                source_id=graphify_source.id,
                start=index,
                end=index,
                text=evidence_text,
            )
        )
        assertions.append(
            Assertion(
                id=stable_id("assertion", source.id, predicate, target.id, evidence_id),
                predicate=predicate,
                subject_id=source.id,
                object_id=target.id,
                evidence_span_id=evidence_id,
                confidence=confidence,
                extractor="graphify",
                graphify_id=str(edge.get("id") or edge.get("key") or index),
                source_path=source_path,
                community=_string_value(edge.get("community") or edge.get("cluster")),
                extraction_source=_graphify_extraction_source(edge),
                confidence_tier=confidence_tier,
                evidence_text=evidence_text,
                metadata=_metadata(edge),
            )
        )

    return ExtractedGraph(
        project_slug=project_slug,
        sources=[graphify_source],
        source_spans=spans,
        entities=list(entities_by_raw_id.values()),
        assertions=assertions,
    )


def apply_community_names(graph: ExtractedGraph, graphify_output_path: Path) -> ExtractedGraph:
    labels = _load_community_labels(graphify_output_path)
    inferred = _infer_community_labels(graph)
    label_map = {**inferred, **labels}
    if not label_map:
        return graph

    entities = []
    for entity in graph.entities:
        community_id = entity.community
        label = label_map.get(str(community_id)) if community_id is not None else None
        if not label:
            entities.append(entity)
            continue
        metadata = dict(entity.metadata)
        metadata.setdefault("community_id", str(community_id))
        entities.append(entity.model_copy(update={"community": label, "metadata": metadata}))

    assertions = []
    for assertion in graph.assertions:
        community_id = assertion.community
        label = label_map.get(str(community_id)) if community_id is not None else None
        if not label:
            assertions.append(assertion)
            continue
        metadata = dict(assertion.metadata)
        metadata.setdefault("community_id", str(community_id))
        assertions.append(
            assertion.model_copy(update={"community": label, "metadata": metadata})
        )

    return graph.model_copy(update={"entities": entities, "assertions": assertions})


def prior_extraction_exists(graphify_output_path: Path) -> bool:
    """True when a previous Graphify extraction is present and reusable by ``graphify update``.

    Requires both ``graph.json`` and the per-file ``cache/`` dir so the incremental path can
    skip unchanged files. When false, the pipeline falls back to a full ``graphify extract``.
    """
    return (graphify_output_path / "graph.json").exists() and (
        graphify_output_path / "cache"
    ).is_dir()


def load_previous_analysis(graphify_output_path: Path) -> dict[str, Any] | None:
    """Load the *second-newest* ``.graphify_analysis.json`` (a prior run's dated snapshot).

    Graphify writes a dated subdir (e.g. ``graphify-out/2026-06-24/``) each run, so the
    newest analysis is the current run and the next one is the baseline for community/cohesion
    diffing. Returns ``None`` when there is no prior snapshot.
    """
    candidates = sorted(
        graphify_output_path.glob("**/.graphify_analysis.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates[1:]:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def load_graphify_analysis(graphify_output_path: Path) -> dict[str, Any] | None:
    """Load Graphify's ``.graphify_analysis.json`` (gods, surprises, communities, cohesion).

    Mirrors :func:`_load_community_labels`'s discovery convention. Returns ``None`` when
    no analysis artifact exists so callers can render a graceful empty state.
    """
    candidates = sorted(
        graphify_output_path.glob("**/.graphify_analysis.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _load_community_labels(graphify_output_path: Path) -> dict[str, str]:
    candidates = sorted(
        graphify_output_path.glob("**/.graphify_labels.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        labels = _labels_from_payload(payload)
        if labels:
            return labels
    return {}


def _labels_from_payload(payload: Any) -> dict[str, str]:
    labels: dict[str, str] = {}
    if isinstance(payload, dict):
        for key in ("communities", "community_labels", "labels"):
            nested = payload.get(key)
            labels.update(_labels_from_payload(nested))
        for key, value in payload.items():
            if isinstance(value, str) and _looks_like_community_id(key):
                labels[str(key)] = value
            elif isinstance(value, dict):
                community_id = (
                    value.get("community")
                    or value.get("community_id")
                    or value.get("cluster")
                    or value.get("id")
                    or key
                )
                label = value.get("label") or value.get("name") or value.get("title")
                if label is not None:
                    labels[str(community_id)] = str(label)
    elif isinstance(payload, list):
        for item in payload:
            labels.update(_labels_from_payload(item))
    return {key: value.strip() for key, value in labels.items() if value.strip()}


def _looks_like_community_id(value: object) -> bool:
    text = str(value)
    return bool(text) and len(text) <= 64


def _infer_community_labels(graph: ExtractedGraph) -> dict[str, str]:
    grouped: dict[str, list[Entity]] = defaultdict(list)
    for entity in graph.entities:
        if entity.community is not None:
            grouped[str(entity.community)].append(entity)

    labels = {}
    for community_id, entities in grouped.items():
        label = _infer_label_from_entities(entities)
        if label:
            labels[community_id] = label
    return labels


def _infer_label_from_entities(entities: list[Entity]) -> str:
    token_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter(entity.type.value for entity in entities)
    for entity in entities:
        for token in _label_tokens(entity.name):
            token_counts[token] += 3
        if entity.source_path:
            for token in _label_tokens(entity.source_path):
                token_counts[token] += 2
        if entity.description:
            for token in _label_tokens(entity.description):
                token_counts[token] += 1

    tokens = [token for token, _ in token_counts.most_common(4)]
    if tokens:
        return " ".join(_display_token(token) for token in tokens)
    entity_types = [entity_type for entity_type, _ in type_counts.most_common(3)]
    return " ".join(entity_types) + " Cluster" if entity_types else ""


COMMUNITY_STOPWORDS = {
    "agent",
    "cache",
    "code",
    "data",
    "file",
    "graph",
    "init",
    "json",
    "main",
    "module",
    "node",
    "none",
    "ontology",
    "package",
    "path",
    "private",
    "project",
    "pytest",
    "repo",
    "root",
    "source",
    "test",
    "tests",
    "tmp",
    "user",
    "users",
    "var",
    "yureeh",
}


def _label_tokens(value: str) -> list[str]:
    tokens = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", value.replace("_", " ")):
        normalized = token.lower()
        if normalized in COMMUNITY_STOPWORDS:
            continue
        if len(normalized) > 28:
            continue
        tokens.append(normalized)
    return tokens


def _display_token(value: str) -> str:
    acronyms = {"api", "aws", "csv", "db", "elo", "gcp", "http", "json", "llm", "sql"}
    if value in acronyms:
        return value.upper()
    return value.capitalize()


def render_graphify_report(
    command: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    *,
    warnings: list[str] | None = None,
    verbose: bool = False,
) -> str:
    lines = ["# Graphify Report", "", f"Command: `{' '.join(command)}`", ""]
    status = "succeeded" if exit_code == 0 else "failed"
    lines.append(f"Status: {status}")
    if stats := _parse_scan_stats(stdout):
        lines.append(
            "Scanned: "
            f"{stats['code']} code, {stats['docs']} docs, "
            f"{stats['papers']} papers, {stats['images']} images"
        )
    if stats := _parse_graph_stats(stdout):
        lines.append(f"Graph: {stats['nodes']} nodes, {stats['edges']} edges")
    if cost := _parse_cost(stdout):
        lines.append(f"Cost: {cost}")
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    if exit_code != 0 and stderr.strip():
        lines.extend(["", "## Error", "", "```text", stderr.strip(), "```"])
    if verbose:
        lines.extend(
            [
                "",
                "## Raw Output",
                "",
                f"Exit code: {exit_code}",
                "",
                "### stdout",
                "",
                "```text",
                stdout.rstrip(),
                "```",
            ]
        )
        if stderr.strip():
            lines.extend(["", "### stderr", "", "```text", stderr.rstrip(), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _parse_scan_stats(output: str) -> dict[str, int] | None:
    match = re.search(
        r"found (?P<code>\d+) code, (?P<docs>\d+) docs, "
        r"(?P<papers>\d+) papers, (?P<images>\d+) images",
        output,
    )
    if not match:
        return None
    return {key: int(value) for key, value in match.groupdict().items()}


def _parse_graph_stats(output: str) -> dict[str, int] | None:
    match = re.search(r"graph\.json: (?P<nodes>\d+) nodes, (?P<edges>\d+) edges", output)
    if not match:
        return None
    return {key: int(value) for key, value in match.groupdict().items()}


def _parse_cost(output: str) -> str | None:
    match = re.search(r"tokens: (?P<cost>.+)", output)
    return match.group("cost").strip() if match else None


def _extract_collection(data: Any, name: str) -> list[Any]:
    if isinstance(data, dict):
        value = data.get(name)
        if isinstance(value, list):
            return value
        graph = data.get("graph")
        if isinstance(graph, dict):
            nested = graph.get(name)
            if isinstance(nested, list):
                return nested
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _entity_type(value: str) -> EntityType:
    normalized = value.strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    for entity_type in EntityType:
        if entity_type.value.lower() == normalized or entity_type.name.lower() == normalized:
            return entity_type
    mapping = {
        "repo": EntityType.system,
        "repository": EntityType.system,
        "service": EntityType.system,
        "symbol": EntityType.function,
        "method": EntityType.function,
        "endpoint": EntityType.api_endpoint,
        "api": EntityType.api_endpoint,
        "model": EntityType.data_model,
        "table": EntityType.data_model,
        "db": EntityType.database,
        "database": EntityType.database,
        "datastore": EntityType.data_store,
        "store": EntityType.data_store,
        "queue": EntityType.queue,
        "external": EntityType.external_service,
        "external_service": EntityType.external_service,
        "deployment": EntityType.deployment_unit,
        "environment": EntityType.environment,
        "config": EntityType.config,
        "secret": EntityType.secret_ref,
        "workflow": EntityType.workflow,
        "role": EntityType.user_role,
    }
    if normalized in mapping:
        return mapping[normalized]
    return EntityType.concept


def _graphify_node_type(node: dict[str, Any], name: str) -> str:
    file_type = str(node.get("file_type") or "").lower()
    origin = str(node.get("_origin") or node.get("origin") or "").lower()
    source_file = str(node.get("source_file") or node.get("file") or "")
    label = name.strip()
    label_lower = label.lower()
    if re.search(r"^(get|post|put|patch|delete)\s+/", label_lower):
        return "endpoint"
    if re.search(r"\b(get|post|put|patch|delete)\s*\(", label_lower) and "/" in label_lower:
        return "endpoint"
    file_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml", ".toml", ".json")
    if label.endswith(file_suffixes):
        return "file"
    if "/" in label and "." in Path(label).name:
        return "file"
    if label.endswith("()"):
        return "function"
    if origin == "ast" and re.search(r"[a-zA-Z_][\w_]*\(\)$", label):
        return "function"
    if file_type == "code" and source_file and label == Path(source_file).name:
        return "file"
    if file_type == "code" and label and label[:1].isupper() and " " not in label:
        return "class"
    if file_type == "docs":
        return "concept"
    return "Concept"


def _string_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _graphify_extraction_source(value: dict[str, Any]) -> str:
    raw = str(
        value.get("extraction_source")
        or value.get("source")
        or value.get("origin")
        or value.get("_origin")
        or value.get("kind")
        or ""
    ).lower()
    if "semantic" in raw or "llm" in raw or "inferred" in raw:
        return "graphify_semantic"
    if "ast" in raw or "code" in raw or "symbol" in raw:
        return "graphify_ast"
    return "graphify"


def _metadata(value: dict[str, Any]) -> dict[str, str | int | float | bool | None]:
    result: dict[str, str | int | float | bool | None] = {}
    for key, item in value.items():
        if isinstance(item, str | int | float | bool) or item is None:
            result[str(key)] = item
    return result


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _confidence(value: Any) -> float:
    if isinstance(value, int | float):
        return max(0.0, min(1.0, float(value)))
    return 0.7


def _confidence_tier(value: dict[str, Any]) -> str:
    raw = str(value.get("confidence") or value.get("confidence_tier") or "").strip().lower()
    if raw in {"extracted", "inferred", "ambiguous", "generated"}:
        return raw
    predicate = str(
        value.get("predicate")
        or value.get("relationship")
        or value.get("relation")
        or value.get("type")
        or value.get("label")
        or ""
    )
    if normalize_predicate(predicate) in {"related_to", "supports"}:
        return "inferred"
    return "extracted"
