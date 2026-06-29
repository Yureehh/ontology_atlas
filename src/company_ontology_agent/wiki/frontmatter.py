from __future__ import annotations

import yaml


def render_frontmatter(data: dict[str, object]) -> str:
    return "---\n" + yaml.safe_dump(data, sort_keys=False).strip() + "\n---\n\n"
