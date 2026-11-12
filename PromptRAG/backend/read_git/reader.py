"""Read a public GitHub repo folder. Read-only: only GET requests to the GitHub API / raw host."""

import json
import re
from collections.abc import Iterator
from urllib.parse import quote

import httpx

from ..config import settings
from ..models import Document

_TEXT_EXT = (".ipynb", ".md", ".txt", ".py")
_URL_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?"
    r"(?:/tree/(?P<ref>[^/]+)(?:/(?P<path>.*))?)?/?$"
)


def parse_github_url(url: str) -> tuple[str, str, str | None, str]:
    """Return (owner, repo, ref or None, folder path) from a github.com URL."""
    m = _URL_RE.match(url.strip())
    if not m:
        raise ValueError(f"Not a recognised GitHub repo/folder URL: {url}")
    return m["owner"], m["repo"], m["ref"], (m["path"] or "").strip("/")


def notebook_to_segments(raw: str) -> list[tuple[str, str]]:
    """(kind, text) parts: markdown cells -> "text", code cells -> "python". Outputs dropped.

    Consecutive cells of the same kind are merged so chunks fill up.
    """
    nb = json.loads(raw)
    segments: list[tuple[str, str]] = []
    for cell in nb.get("cells", []):
        src = "".join(cell.get("source", [])).strip()
        if not src:
            continue
        kind = "python" if cell.get("cell_type") == "code" else "text"
        if segments and segments[-1][0] == kind:
            segments[-1] = (kind, segments[-1][1] + "\n\n" + src)
        else:
            segments.append((kind, src))
    return segments


def notebook_to_text(raw: str) -> str:
    """Whole notebook as one string: markdown as-is, code cells fenced."""
    return "\n\n".join(
        f"```python\n{t}\n```" if k == "python" else t for k, t in notebook_to_segments(raw)
    )


def iter_documents(url: str | None = None) -> Iterator[Document]:
    url = url or settings.git_repo_url
    owner, repo, ref, folder = parse_github_url(url)

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "promptrag-reader"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        if ref is None:
            r = client.get(f"https://api.github.com/repos/{owner}/{repo}")
            r.raise_for_status()
            ref = r.json()["default_branch"]

        r = client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{quote(ref)}",
            params={"recursive": "1"},
        )
        r.raise_for_status()
        tree = r.json()
        if tree.get("truncated"):
            print("  warning: GitHub tree listing was truncated")

        prefix = f"{folder}/" if folder else ""
        paths = sorted(
            e["path"]
            for e in tree["tree"]
            if e["type"] == "blob"
            and e["path"].startswith(prefix)
            and e["path"].lower().endswith(_TEXT_EXT)
        )

        for path in paths:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{quote(ref)}/{quote(path)}"
            resp = client.get(raw_url)
            resp.raise_for_status()
            lower = path.lower()
            if lower.endswith(".ipynb"):
                segments = notebook_to_segments(resp.text)
                text = notebook_to_text(resp.text)
            elif lower.endswith(".py"):
                segments = [("python", resp.text)]
                text = resp.text
            else:  # .md / .txt
                segments = None
                text = resp.text
            yield Document(
                source_type="git",
                source=path,
                text=text,
                metadata={"repo": f"{owner}/{repo}", "ref": ref},
                segments=segments,
            )
