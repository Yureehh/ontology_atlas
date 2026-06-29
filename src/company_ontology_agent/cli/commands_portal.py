from __future__ import annotations

import http.server
import os
import socketserver

import typer

from company_ontology_agent.config.project_config import find_project_root, load_project_config
from company_ontology_agent.portal.builder import PortalBuilder
from company_ontology_agent.workflows.build_graph import repository_for

portal_app = typer.Typer(help="Manager demo portal operations.")


@portal_app.command("build")
def portal_build(dry_run: bool = typer.Option(True, "--dry-run/--neo4j")) -> None:
    root = find_project_root()
    config = load_project_config(root)
    graph = repository_for(root, config, dry_run=dry_run).read_graph(config.project_slug)
    files = PortalBuilder().build(
        graph,
        root,
        root / "portal",
        display_name=config.project_name,
    )
    typer.echo(f"Built portal: {len(files)} files")
    typer.echo(f"Open: {root / 'portal' / 'index.html'}")


@portal_app.command("serve")
def portal_serve(port: int = typer.Option(8765, "--port")) -> None:
    root = find_project_root()
    portal_path = root / "portal"
    if not (portal_path / "index.html").exists():
        raise RuntimeError("Portal has not been built. Run `ontology-agent portal build` first.")
    os.chdir(root)
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("127.0.0.1", port), handler) as server:
        typer.echo(f"Serving portal at http://127.0.0.1:{port}/portal/index.html")
        server.serve_forever()
