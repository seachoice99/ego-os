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


def test_post_with_matching_origin_is_accepted(app_client, owner_credentials, csrf_headers):
    response = app_client.post(
        "/tasks",
        data={"request_text": "matching origin", "project_id": 1},
        auth=owner_credentials,
        headers=csrf_headers,
    )
    # TestClient follows the 303 -> Location by default, landing on the
    # (now-queued, v0.4.1) task page; a CSRF rejection would have stopped
    # at 403 instead. The lifecycle itself isn't run in this test -- that's
    # covered by test_smoke.py -- this only proves the CSRF check passed.
    assert response.status_code == 200


def test_post_with_matching_referer_is_accepted_without_origin(app_client, owner_credentials):
    """Some legitimate clients send Referer but not Origin -- the check
    falls back to Referer rather than requiring both."""
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
