"""Safe ZIP/PDF processing (v0.4.1): zip-slip, zip-bomb, entry-count,
PDF page-count, and corrupted-file protection inside
tools._build_presentation_site, plus cleanup-on-failure (no partial
source/site directory left behind after a rejection).
"""

import io
import zipfile

import pytest


def _write_upload(temp_env, task_id, filename, content: bytes):
    upload_dir = temp_env["uploads_dir"] / str(task_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / filename).write_bytes(content)


def _real_png_bytes(width=40, height=30, color=(200, 50, 50)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, "PNG")
    return buf.getvalue()


def _real_pdf_bytes(pages=1) -> bytes:
    import fitz

    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page(width=200, height=100)
        page.draw_rect(page.rect, color=None, fill=(0.2, 0.3, 0.5))
    data = doc.tobytes()
    doc.close()
    return data


def _source_site_dirs(temp_env, task_id):
    task_dir = temp_env["generated_dir"] / str(task_id)
    return task_dir / "source", task_dir / "site"


def test_regular_zip_builds_a_site_regression(temp_env):
    from ego_os import tools

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("s001.png", _real_png_bytes())
        zf.writestr("s002.png", _real_png_bytes(color=(50, 200, 80)))
    _write_upload(temp_env, 1, "deck.zip", buf.getvalue())

    result = tools._build_presentation_site("regression-check", ["Cover", "Team"], 1)
    assert "2 slides" in result
    published = temp_env["presentations_dir"] / "regression-check" / "index.html"
    assert published.exists()


def test_zip_slip_entry_is_rejected_not_extracted_outside_sandbox(temp_env, tmp_path):
    from ego_os import tools

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("s001.png", _real_png_bytes())  # legitimate
        zf.writestr("../../../evil.png", _real_png_bytes())  # traversal attempt
    _write_upload(temp_env, 2, "deck.zip", buf.getvalue())

    result = tools._build_presentation_site("slip-check", [], 2)
    assert "1 slides" in result  # the traversal entry was rejected outright, not flattened in
    # The traversal target must not exist anywhere outside the sandbox,
    # and must not have been silently accepted under its flattened basename either.
    assert not (tmp_path / "evil.png").exists()
    assert not (tools.GENERATED_DIR.parent / "evil.png").exists()
    source_dir, _ = _source_site_dirs(temp_env, 2)
    assert not (source_dir / "evil.png").exists()


def test_zip_with_too_many_entries_is_rejected_and_cleaned_up(temp_env, monkeypatch):
    from ego_os import tools

    monkeypatch.setattr(tools, "_MAX_ZIP_ENTRIES", 3)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(5):
            zf.writestr(f"s{i:03d}.png", _real_png_bytes())
    _write_upload(temp_env, 3, "deck.zip", buf.getvalue())

    with pytest.raises(tools.ToolError, match="too many entries"):
        tools._build_presentation_site("too-many-entries", [], 3)

    source_dir, site_dir = _source_site_dirs(temp_env, 3)
    assert not source_dir.exists()
    assert not site_dir.exists()


def test_zip_bomb_total_size_is_rejected_and_cleaned_up(temp_env, monkeypatch):
    from ego_os import tools

    monkeypatch.setattr(tools, "_MAX_ZIP_TOTAL_UNCOMPRESSED_BYTES", 1000)  # tiny cap
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Content doesn't need to be a real, decodable PNG -- the size cap
        # is enforced during zip extraction itself, before anything is
        # ever handed to Pillow. Raw filler bytes past the cap is enough.
        zf.writestr("s001.png", b"x" * 2000)
    _write_upload(temp_env, 4, "deck.zip", buf.getvalue())

    with pytest.raises(tools.ToolError, match="zip bomb"):
        tools._build_presentation_site("bomb-check", [], 4)

    source_dir, site_dir = _source_site_dirs(temp_env, 4)
    assert not source_dir.exists()
    assert not site_dir.exists()


def test_corrupted_zip_is_rejected_cleanly(temp_env):
    from ego_os import tools

    _write_upload(temp_env, 5, "deck.zip", b"this is not a real zip file at all")

    with pytest.raises(tools.ToolError, match="corrupted"):
        tools._build_presentation_site("corrupt-zip-check", [], 5)

    source_dir, site_dir = _source_site_dirs(temp_env, 5)
    assert not source_dir.exists()
    assert not site_dir.exists()


def test_corrupted_pdf_is_rejected_cleanly(temp_env):
    from ego_os import tools

    _write_upload(temp_env, 6, "deck.pdf", b"this is not a real pdf file at all")

    with pytest.raises(tools.ToolError, match="corrupted"):
        tools._build_presentation_site("corrupt-pdf-check", [], 6)

    source_dir, site_dir = _source_site_dirs(temp_env, 6)
    assert not source_dir.exists()
    assert not site_dir.exists()


def test_pdf_over_page_limit_is_rejected_and_cleaned_up(temp_env, monkeypatch):
    from ego_os import tools

    monkeypatch.setattr(tools, "_MAX_PDF_PAGES", 2)
    _write_upload(temp_env, 7, "deck.pdf", _real_pdf_bytes(pages=3))

    with pytest.raises(tools.ToolError, match="page limit"):
        tools._build_presentation_site("page-limit-check", [], 7)

    source_dir, site_dir = _source_site_dirs(temp_env, 7)
    assert not source_dir.exists()
    assert not site_dir.exists()


def test_pdf_within_page_limit_still_works_regression(temp_env, monkeypatch):
    from ego_os import tools

    monkeypatch.setattr(tools, "_MAX_PDF_PAGES", 5)
    _write_upload(temp_env, 8, "deck.pdf", _real_pdf_bytes(pages=3))

    result = tools._build_presentation_site("within-limit-check", [], 8)
    assert "3 slides" in result
