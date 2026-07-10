"""Safe file intake (v0.4.1): extension allowlist, real file-type
signature check, size cap, and "no orphaned task on a rejected upload" --
all enforced in ego_os.main before a task row is ever created.
"""

import io
import zipfile

import pytest


def _real_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("s001.png", b"not a real png but a real zip entry")
    return buf.getvalue()


def _real_pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    doc.new_page(width=200, height=100)
    data = doc.tobytes()
    doc.close()
    return data


def test_wrong_extension_is_rejected_and_creates_no_task(app_client, owner_credentials, csrf_headers):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "attach a script", "project_id": 1},
        files={"attachment": ("payload.txt", b"just text", "text/plain")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 400
    assert store.get_tasks() == []


def test_extension_zip_but_content_is_not_a_zip_is_rejected(app_client, owner_credentials, csrf_headers):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "fake zip", "project_id": 1},
        files={"attachment": ("deck.zip", b"this is plain text, not a zip", "application/zip")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 400
    assert store.get_tasks() == []


def test_extension_pdf_but_content_is_not_a_pdf_is_rejected(app_client, owner_credentials, csrf_headers):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "fake pdf", "project_id": 1},
        files={"attachment": ("deck.pdf", b"this is plain text, not a pdf", "application/pdf")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 400
    assert store.get_tasks() == []


def test_empty_attachment_is_rejected(app_client, owner_credentials, csrf_headers):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "empty file", "project_id": 1},
        files={"attachment": ("deck.zip", b"", "application/zip")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 400
    assert store.get_tasks() == []


def test_oversized_attachment_is_rejected(app_client, owner_credentials, csrf_headers, monkeypatch):
    from ego_os import main, store

    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)  # tiny cap, fast test
    response = app_client.post(
        "/tasks",
        data={"request_text": "too big", "project_id": 1},
        files={"attachment": ("deck.zip", _real_zip_bytes(), "application/zip")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 413
    assert store.get_tasks() == []


def test_valid_real_zip_is_accepted_and_staged_under_the_new_task(app_client, owner_credentials, csrf_headers, temp_env):
    from ego_os import store

    # Not processed here (that's test_smoke.py's job) -- this only checks
    # that a valid upload is accepted and correctly staged under the new
    # task's id, so the task stays 'queued' and that's fine.
    response = app_client.post(
        "/tasks",
        data={"request_text": "As Designer, note the attachment", "project_id": 1},
        files={"attachment": ("deck.zip", _real_zip_bytes(), "application/zip")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 200
    tasks = store.get_tasks()
    assert len(tasks) == 1
    uploaded = list((temp_env["uploads_dir"] / str(tasks[0]["id"])).glob("*.zip"))
    assert len(uploaded) == 1
    # No leftover staging directories from the validate-before-create step.
    assert list(temp_env["uploads_dir"].glob("_staging-*")) == []


def test_valid_real_pdf_is_accepted(app_client, owner_credentials, csrf_headers, temp_env):
    from ego_os import store

    response = app_client.post(
        "/tasks",
        data={"request_text": "As Designer, note the attachment", "project_id": 1},
        files={"attachment": ("deck.pdf", _real_pdf_bytes(), "application/pdf")},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    assert response.status_code == 200
    tasks = store.get_tasks()
    uploaded = list((temp_env["uploads_dir"] / str(tasks[0]["id"])).glob("*.pdf"))
    assert len(uploaded) == 1
