"""Tool Framework (v0.2, first capability).

The general mechanism by which an employee is granted a specific external
capability without ever holding a credential directly, per the Boundaries
section of architecture/005_EMPLOYEE_MODEL.md: an employee references a tool
by name; this module is the only place that resolves what that name actually
does and whether the employee's declared `permissions` allow it.

Adding a new tool later (web search, document generation, spreadsheet
editing) means adding an entry to TOOLS, not changing this framework.
"""

import os
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).parent.parent.resolve()
TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Paths a tool must never touch, even for an employee with write_repository --
# these hold credentials or version-control internals, not task output.
_DENYLIST = {".env", ".git"}


class ToolError(Exception):
    """Raised when a tool cannot or must not run: bad arguments, a path
    outside the repository, or a denylisted path."""


def _resolve_repo_path(path: str) -> Path:
    target = (REPO_ROOT / path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        raise ToolError(f"path '{path}' is outside the repository and cannot be accessed")
    if target.name in _DENYLIST or any(part in _DENYLIST for part in target.relative_to(REPO_ROOT).parts):
        raise ToolError(f"path '{path}' is not accessible to tools")
    return target


def _read_repository_file(path: str) -> str:
    target = _resolve_repo_path(path)
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    return target.read_text(encoding="utf-8")


def _write_repository_file(path: str, content: str) -> str:
    target = _resolve_repo_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {path}"


def _web_search(query: str) -> str:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ToolError("TAVILY_API_KEY is not configured in .env")

    response = httpx.post(
        TAVILY_SEARCH_URL,
        json={"api_key": api_key, "query": query, "max_results": 5},
        timeout=20,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    if not results:
        return "No results found."

    lines = []
    for r in results:
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = r.get("content", "")
        lines.append(f"- {title} ({url})\n  {snippet}")
    return "\n".join(lines)


TOOLS = {
    "read_repository_file": {
        "permission": "read_repository",
        "description": (
            'read_repository_file(path): read a text file from this repository. '
            'Args as JSON: {"path": "relative/path.ext"}'
        ),
        "fn": _read_repository_file,
    },
    "write_repository_file": {
        "permission": "write_repository",
        "description": (
            'write_repository_file(path, content): create or overwrite a text file in this '
            'repository. Args as JSON: {"path": "relative/path.ext", "content": "..."}'
        ),
        "fn": _write_repository_file,
    },
    "web_search": {
        "permission": "use_web",
        "description": (
            'web_search(query): search the live web and return up to 5 results, each with a '
            'title, url, and content snippet. Args as JSON: {"query": "search terms"}'
        ),
        "fn": _web_search,
    },
}


def available_tools(permissions):
    """Tools an employee with this permission list is allowed to see and use."""
    return [tool for tool in TOOLS.values() if tool["permission"] in permissions]


def call_tool(permissions, tool_name: str, **kwargs):
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise ToolError(f"unknown tool: {tool_name}")
    if tool["permission"] not in permissions:
        raise ToolError(
            f"tool '{tool_name}' requires permission '{tool['permission']}', which this employee does not have"
        )
    return tool["fn"](**kwargs)
