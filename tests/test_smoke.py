"""Validates the test harness itself: isolated DB, mocked model provider,
a real HTTP request through FastAPI's TestClient exercising the actual
Task Lifecycle end to end. If this fails, no other test in this suite can
be trusted -- it's the harness's own regression test, not a feature test.
"""


def test_harness_uses_isolated_db_not_real_one(temp_env):
    from ego_os import store

    assert store.DB_PATH == temp_env["db_path"]
    assert not temp_env["db_path"].exists()  # nothing written yet
    store.init_db()
    assert temp_env["db_path"].exists()


def test_command_page_loads(app_client, owner_credentials):
    response = app_client.get("/", auth=owner_credentials)
    assert response.status_code == 200


def test_full_task_lifecycle_with_mocked_model(app_client, owner_credentials, csrf_headers, fake_model_complete):
    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("A short note for the Owner.", 20, 10, 0.0001)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    response = app_client.post(
        "/tasks",
        data={"request_text": "Write a short note", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "A short note for the Owner." in response.text

    # No real network call happened -- every model call was served by the fake.
    capabilities_called = {call[0] for call in fake_model_complete.calls}
    assert capabilities_called == {"delegation", "business_communication", "critique"}
