from __future__ import annotations

import re


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
    lines.append(f"Status: {'succeeded' if exit_code == 0 else 'failed'}")
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
    return {key: int(value) for key, value in match.groupdict().items()} if match else None


def _parse_graph_stats(output: str) -> dict[str, int] | None:
    match = re.search(r"graph\.json: (?P<nodes>\d+) nodes, (?P<edges>\d+) edges", output)
    return {key: int(value) for key, value in match.groupdict().items()} if match else None


def _parse_cost(output: str) -> str | None:
    match = re.search(r"tokens: (?P<cost>.+)", output)
    return match.group("cost").strip() if match else None
