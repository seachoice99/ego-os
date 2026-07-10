"""CSRF-equivalent protection (v0.4.1): Origin/Referer verification on
every state-changing request, chosen over a session/token scheme since
Basic Auth carries no session to hold a synchronizer token in."""


def test_post_without_origin_or_referer_is_rejected(app_client, owner_credentials):
    response = app_client.post(
        "/tasks",
        data={"request_text": "no origin header", "project_id": 1},
        auth=owner_credentials,
    )
    assert response.status_code == 403


def test_post_with_mismatched_origin_is_rejected(app_client, owner_credentials):
    response = app_client.post(
        "/tasks",
        data={"request_text": "wrong origin", "project_id": 1},
        auth=owner_credentials,
        headers={"origin": "https://attacker.example"},
    )
    assert response.status_code == 403


def test_post_with_matching_origin_is_accepted(app_client, owner_credentials, csrf_headers, fake_model_complete):
    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    response = app_client.post(
        "/tasks",
        data={"request_text": "matching origin", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    # TestClient follows the 303 -> Location by default, landing on the
    # delivered task page; a CSRF rejection would have stopped at 403 instead.
    assert response.status_code == 200


def test_post_with_matching_referer_is_accepted_without_origin(app_client, owner_credentials, fake_model_complete):
    """Some legitimate clients send Referer but not Origin -- the check
    falls back to Referer rather than requiring both."""
    fake_model_complete.responses["delegation"] = ("writer", 5, 1, 0.00001)
    fake_model_complete.responses["business_communication"] = ("Done.", 10, 5, 0.00005)
    fake_model_complete.responses["critique"] = ("PASS", 5, 1, 0.00001)

    response = app_client.post(
        "/tasks",
        data={"request_text": "referer fallback", "project_id": 1},
        auth=owner_credentials,
        headers={"referer": "http://testserver/"},
    )
    assert response.status_code == 200


def test_get_requests_are_not_csrf_checked(app_client, owner_credentials):
    """Origin/Referer verification only applies to state-changing
    methods -- a plain GET must not require it."""
    response = app_client.get("/", auth=owner_credentials)
    assert response.status_code == 200
