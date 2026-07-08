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
from docx import Document
from fpdf import FPDF

REPO_ROOT = Path(__file__).parent.parent.resolve()
GENERATED_DIR = Path(__file__).parent / "generated"
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_DOCUMENT_FORMATS = {".md", ".docx", ".pdf"}

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


def _write_markdown(target: Path, content: str) -> None:
    target.write_text(content, encoding="utf-8")


def _write_docx(target: Path, content: str) -> None:
    """Minimal markdown-ish -> docx conversion: '# '/'## ' headings, '- '
    bullets, everything else a paragraph. Not a full markdown renderer --
    enough structure for a real, readable Word document."""
    doc = Document()
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            doc.add_heading(stripped[3:], level=2)
        elif stripped.startswith("# "):
            doc.add_heading(stripped[2:], level=1)
        elif stripped.startswith("- "):
            doc.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped:
            doc.add_paragraph(stripped)
    doc.save(target)


_UNICODE_TO_LATIN1 = {
    "—": "-", "–": "-",  # em/en dash
    "‘": "'", "’": "'",  # curly single quotes
    "“": '"', "”": '"',  # curly double quotes
    "…": "...",
    "•": "-",  # bullet
}


def _latin1_safe(text: str) -> str:
    """The PDF core font (Helvetica) only supports Latin-1/WinAnsi, but
    LLM output routinely contains em-dashes, curly quotes, and bullet
    characters -- found live during verification (raised
    FPDFUnicodeEncodingException). Transliterate the common ones, then
    drop anything still unsupported rather than crashing generation."""
    for unicode_char, replacement in _UNICODE_TO_LATIN1.items():
        text = text.replace(unicode_char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _write_pdf(target: Path, content: str) -> None:
    """Same minimal heading/bullet/paragraph structure as _write_docx,
    rendered with the PDF core font (latin-1 only, so a plain '-' bullet
    rather than a unicode glyph).

    Every multi_cell call must explicitly return the cursor to the left
    margin (new_x="LMARGIN"): fpdf2 defaults new_x to the *right* edge, so
    without this the next call starts with almost no width left on the
    line and raises "Not enough horizontal space to render a single
    character" -- found live during Document Generation verification."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in content.splitlines():
        stripped = _latin1_safe(line.strip())
        if stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(0, 8, stripped[3:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=12)
        elif stripped.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 10, stripped[2:], new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=12)
        elif stripped.startswith("- "):
            pdf.multi_cell(0, 8, f"- {stripped[2:]}", new_x="LMARGIN", new_y="NEXT")
        elif stripped:
            pdf.multi_cell(0, 8, stripped, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.ln(4)
    pdf.output(str(target))


def _create_document(filename: str, content: str, task_id: int) -> str:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise ToolError("filename must not contain path separators")
    ext = Path(filename).suffix.lower()
    if ext not in _DOCUMENT_FORMATS:
        raise ToolError(f"unsupported document format '{ext or filename}' -- use .md, .docx, or .pdf")

    task_dir = GENERATED_DIR / str(task_id)
    task_dir.mkdir(parents=True, exist_ok=True)
    target = task_dir / filename

    if ext == ".md":
        _write_markdown(target, content)
    elif ext == ".docx":
        _write_docx(target, content)
    elif ext == ".pdf":
        _write_pdf(target, content)

    return f"created document artifact '{filename}', downloadable from the task's report."


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
    "create_document": {
        "permission": "create_documents",
        "needs_context": ["task_id"],
        "description": (
            'create_document(filename, content): generate a real, downloadable document artifact. '
            "filename must end in .md, .docx, or .pdf. content is plain text where lines starting "
            "with '# ' or '## ' become headings and '- ' becomes a bullet. "
            'Args as JSON: {"filename": "name.pdf", "content": "# Title\\n\\nBody text..."}'
        ),
        "fn": _create_document,
    },
}


def available_tools(permissions):
    """Tools an employee with this permission list is allowed to see and use."""
    return [tool for tool in TOOLS.values() if tool["permission"] in permissions]


def call_tool(permissions, tool_name: str, context=None, **kwargs):
    """context carries values a tool needs but an LLM's TOOL_REQUEST can't
    reasonably supply itself (e.g. which task a generated document belongs
    to) -- only merged in for a tool that declares it wants that key via
    `needs_context`, so existing tools are unaffected."""
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise ToolError(f"unknown tool: {tool_name}")
    if tool["permission"] not in permissions:
        raise ToolError(
            f"tool '{tool_name}' requires permission '{tool['permission']}', which this employee does not have"
        )
    for key in tool.get("needs_context", []):
        if context and key in context:
            kwargs[key] = context[key]
    return tool["fn"](**kwargs)
