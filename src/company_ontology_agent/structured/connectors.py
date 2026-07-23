from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from company_ontology_agent.config.project_config import DatasetConfig
from company_ontology_agent.structured.models import StructuredDataset, StructuredRecord


def load_dataset(project_root: Path, config: DatasetConfig) -> StructuredDataset:
    connector = config.connector.lower()
    if connector == "csv":
        return CsvConnector().load(project_root, config)
    if connector in {"json", "jsonl"}:
        return JsonConnector().load(project_root, config)
    if connector == "sqlite":
        return SqliteConnector().load(project_root, config)
    if connector == "parquet":
        return ParquetConnector().load(project_root, config)
    if connector in {"postgres", "postgresql", "aurora"}:
        return PostgresConnector().load(project_root, config)
    raise ValueError(f"Unsupported structured connector: {config.connector}")


class CsvConnector:
    def load(self, project_root: Path, config: DatasetConfig) -> StructuredDataset:
        path = _resolve_path(project_root, config.path)
        rows = list(_read_csv(path))
        _validate_columns(path.stem, rows[0].keys() if rows else [], config.required_columns)
        records = [
            StructuredRecord(
                source=path.stem,
                row_number=index,
                values=_record_values(dict(row), path=path, source=path.stem),
            )
            for index, row in enumerate(_limit_rows(rows, config.row_limit), start=1)
        ]
        return StructuredDataset(
            name=config.name,
            domain=config.domain,
            connector=config.connector,
            records_by_source={path.stem: records},
        )


class JsonConnector:
    def load(self, project_root: Path, config: DatasetConfig) -> StructuredDataset:
        path = _resolve_path(project_root, config.path)
        if path.suffix.lower() == ".jsonl":
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("records", [])
        _validate_columns(path.stem, rows[0].keys() if rows else [], config.required_columns)
        records = [
            StructuredRecord(
                source=path.stem,
                row_number=index,
                values=_record_values(dict(row), path=path, source=path.stem),
            )
            for index, row in enumerate(_limit_rows(rows, config.row_limit), start=1)
        ]
        return StructuredDataset(
            name=config.name,
            domain=config.domain,
            connector=config.connector,
            records_by_source={path.stem: records},
        )


class SqliteConnector:
    def load(self, project_root: Path, config: DatasetConfig) -> StructuredDataset:
        path = _resolve_path(project_root, config.path)
        tables = config.include_tables or _sqlite_tables(path)
        records_by_source: dict[str, list[StructuredRecord]] = {}
        with sqlite3.connect(path) as connection:
            connection.row_factory = sqlite3.Row
            for table in tables:
                rows = connection.execute(f'SELECT * FROM "{table}"').fetchall()
                _validate_columns(table, rows[0].keys() if rows else [], config.required_columns)
                records_by_source[table] = [
                    StructuredRecord(
                        source=table,
                        row_number=index,
                        values=_record_values(dict(row), path=path, source=table),
                    )
                    for index, row in enumerate(_limit_rows(rows, config.row_limit), start=1)
                ]
        return StructuredDataset(
            name=config.name,
            domain=config.domain,
            connector=config.connector,
            records_by_source=records_by_source,
        )


class PostgresConnector:
    def load(self, project_root: Path, config: DatasetConfig) -> StructuredDataset:
        del project_root
        uri = os.getenv(config.uri_env or "")
        if not uri:
            raise RuntimeError(f"{config.uri_env} is required for dataset {config.name}")
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "PostgreSQL/Aurora connector requires psycopg. Install a postgres extra "
                "or use CSV/JSON/SQLite for local validation."
            ) from exc
        if not config.include_tables:
            raise RuntimeError("PostgreSQL connector requires include_tables for V1.1")
        records_by_source: dict[str, list[StructuredRecord]] = {}
        with psycopg.connect(uri) as connection:
            with connection.cursor() as cursor:
                for table in config.include_tables:
                    cursor.execute(f'SELECT * FROM "{table}"')
                    columns = [column.name for column in cursor.description]
                    _validate_columns(table, columns, config.required_columns)
                    records_by_source[table] = [
                        StructuredRecord(
                            source=table,
                            row_number=index,
                            values=_record_values(
                                dict(zip(columns, row, strict=False)),
                                path=Path(config.uri_env or config.name),
                                source=table,
                            ),
                        )
                        for index, row in enumerate(
                            _limit_rows(cursor.fetchall(), config.row_limit), start=1
                        )
                    ]
        return StructuredDataset(
            name=config.name,
            domain=config.domain,
            connector=config.connector,
            records_by_source=records_by_source,
        )


class ParquetConnector:
    def load(self, project_root: Path, config: DatasetConfig) -> StructuredDataset:
        path = _resolve_path(project_root, config.path)
        try:
            parquet_module: Any = __import__("pyarrow.parquet", fromlist=["read_table"])
        except ImportError as exc:
            raise RuntimeError(
                "Parquet datasets require the optional parquet extra. Install with "
                "`uv tool install --force '.[parquet]'` from the Ontology Atlas repo."
            ) from exc
        table = parquet_module.read_table(path)
        columns = table.column_names
        _validate_columns(path.stem, columns, config.required_columns)
        if config.row_limit is not None:
            table = table.slice(0, config.row_limit)
        rows = table.to_pylist()
        records = [
            StructuredRecord(
                source=path.stem,
                row_number=index,
                values=_record_values(dict(row), path=path, source=path.stem),
            )
            for index, row in enumerate(rows, start=1)
        ]
        return StructuredDataset(
            name=config.name,
            domain=config.domain,
            connector=config.connector,
            records_by_source={path.stem: records},
        )


def _resolve_path(project_root: Path, path: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate


def _read_csv(path: Path) -> Iterable[dict[str, object]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            yield {key: _csv_scalar(value) for key, value in row.items()}


def _csv_scalar(value: str | None) -> object:
    if value is None or value == "":
        return ""
    folded = value.casefold()
    if folded in {"true", "false"}:
        return folded == "true"
    if value.isdigit() and (value == "0" or not value.startswith("0")):
        return int(value)
    try:
        return float(value) if any(character in value for character in ".eE") else value
    except ValueError:
        return value


def _sqlite_tables(path: Path) -> list[str]:
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    return [row[0] for row in rows]


def _limit_rows[T](rows: Sequence[T], row_limit: int | None) -> Sequence[T]:
    if row_limit is None:
        return rows
    return rows[:row_limit]


def _validate_columns(source: str, columns: Iterable[str], required_columns: list[str]) -> None:
    available = set(columns) | {"__source", "__path", "__parent", "__grandparent"}
    missing = sorted(set(required_columns) - available)
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def _record_values(values: dict[str, object], *, path: Path, source: str) -> dict[str, object]:
    return {
        **values,
        "__source": source,
        "__path": str(path),
        "__parent": path.parent.name,
        "__grandparent": path.parent.parent.name,
    }
