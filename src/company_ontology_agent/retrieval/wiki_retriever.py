from __future__ import annotations

from pathlib import Path


def retrieve_wiki_context(wiki_path: Path, question: str, top_k: int = 8) -> list[dict[str, str]]:
    terms = {term.lower() for term in question.split() if len(term) > 3}
    matches: list[dict[str, str]] = []
    if not wiki_path.exists():
        return matches
    for page in sorted(wiki_path.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        if any(term in text.lower() for term in terms):
            matches.append({"path": str(page), "text": text[:1000]})
    return matches[:top_k]
