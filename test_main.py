"""Tests for main.py – all Firebase and external HTTP calls are mocked."""
import sys
import types
import base64
import datetime as dt
from unittest import mock
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Bootstrap: mock firebase_admin before main.py is imported so that the
# module-level initialisation code does not try to connect to Firebase.
# ---------------------------------------------------------------------------

# Minimal firebase_admin stub
firebase_stub = types.ModuleType("firebase_admin")
firebase_stub.initialize_app = MagicMock()

credentials_stub = types.ModuleType("firebase_admin.credentials")
credentials_stub.Certificate = MagicMock(return_value=MagicMock())

_mock_db = MagicMock()
firestore_stub = types.ModuleType("firebase_admin.firestore")
firestore_stub.client = MagicMock(return_value=_mock_db)

_mock_bucket = MagicMock()
storage_stub = types.ModuleType("firebase_admin.storage")
storage_stub.bucket = MagicMock(return_value=_mock_bucket)

auth_stub = types.ModuleType("firebase_admin.auth")
auth_stub.verify_id_token = MagicMock(return_value={"uid": "user123"})

sys.modules["firebase_admin"] = firebase_stub
sys.modules["firebase_admin.credentials"] = credentials_stub
sys.modules["firebase_admin.firestore"] = firestore_stub
sys.modules["firebase_admin.storage"] = storage_stub
sys.modules["firebase_admin.auth"] = auth_stub

# Provide a fake GOOGLE_APPLICATION_CREDENTIALS so the RuntimeError is not raised
import os
os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "/fake/creds.json")

# Now import the app (Firebase is mocked at this point)
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

# Inject the mocked db / bucket directly into the module so tests can
# configure them per-test without re-importing.
main.db = _mock_db
main.bucket = _mock_bucket

client = TestClient(main.app)

VALID_TOKEN = "Bearer valid-token"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def auth_headers():
    return {"Authorization": VALID_TOKEN}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert isinstance(body["ts"], int)


# ---------------------------------------------------------------------------
# Authentication guard
# ---------------------------------------------------------------------------

class TestAuth:
    def test_missing_token_returns_401(self):
        resp = client.get("/cases")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        auth_stub.verify_id_token.side_effect = Exception("bad token")
        try:
            resp = client.get("/cases", headers={"Authorization": "Bearer bad"})
            assert resp.status_code == 401
        finally:
            auth_stub.verify_id_token.side_effect = None
            auth_stub.verify_id_token.return_value = {"uid": "user123"}


# ---------------------------------------------------------------------------
# POST /cases
# ---------------------------------------------------------------------------

class TestCreateCase:
    def test_create_case_returns_id(self):
        mock_ref = MagicMock()
        mock_ref.id = "case-abc"
        mock_update_time = MagicMock()
        _mock_db.collection.return_value.add.return_value = (mock_update_time, mock_ref)

        resp = client.post(
            "/cases",
            json={"title": "Test Case", "description": "A test"},
            headers=auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "case-abc"
        assert body["title"] == "Test Case"
        assert body["owner_uid"] == "user123"

    def test_create_case_no_body(self):
        mock_ref = MagicMock()
        mock_ref.id = "case-xyz"
        mock_update_time = MagicMock()
        _mock_db.collection.return_value.add.return_value = (mock_update_time, mock_ref)

        resp = client.post("/cases", headers=auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "case-xyz"
        assert "title" not in body


# ---------------------------------------------------------------------------
# GET /cases
# ---------------------------------------------------------------------------

class TestListCases:
    def test_list_cases_empty(self):
        mock_stream = iter([])
        _mock_db.collection.return_value.where.return_value.stream.return_value = mock_stream

        resp = client.get("/cases", headers=auth_headers())
        assert resp.status_code == 200
        assert resp.json() == {"cases": []}

    def test_list_cases_with_results(self):
        doc = MagicMock()
        doc.id = "case-1"
        doc.to_dict.return_value = {"owner_uid": "user123", "title": "My Case"}
        _mock_db.collection.return_value.where.return_value.stream.return_value = iter([doc])

        resp = client.get("/cases", headers=auth_headers())
        assert resp.status_code == 200
        cases = resp.json()["cases"]
        assert len(cases) == 1
        assert cases[0]["id"] == "case-1"
        assert cases[0]["title"] == "My Case"


# ---------------------------------------------------------------------------
# GET /cases/{case_id}
# ---------------------------------------------------------------------------

class TestGetCase:
    def test_get_case_not_found(self):
        mock_doc = MagicMock()
        mock_doc.exists = False
        _mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        resp = client.get("/cases/missing", headers=auth_headers())
        assert resp.status_code == 404

    def test_get_case_wrong_owner(self):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"owner_uid": "other-user"}
        _mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        resp = client.get("/cases/case-1", headers=auth_headers())
        assert resp.status_code == 403

    def test_get_case_success(self):
        mock_doc = MagicMock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {"owner_uid": "user123", "title": "Found"}
        _mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        resp = client.get("/cases/case-1", headers=auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "case-1"
        assert body["title"] == "Found"


# ---------------------------------------------------------------------------
# GET /canary/{case_id}
# ---------------------------------------------------------------------------

class TestCanary:
    def test_canary_not_found(self):
        mock_doc = MagicMock()
        mock_doc.exists = False
        _mock_db.collection.return_value.document.return_value.get.return_value = mock_doc

        resp = client.get("/canary/missing")
        assert resp.status_code == 404

    def test_canary_returns_gif(self):
        mock_doc = MagicMock()
        mock_doc.exists = True
        _mock_db.collection.return_value.document.return_value.get.return_value = mock_doc
        _mock_db.collection.return_value.document.return_value.collection.return_value.add = MagicMock()

        resp = client.get("/canary/case-1")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/gif"
        pixel_gif = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEHAAEALAAAAAABAAEAAAICTAEAOw==")
        assert resp.content == pixel_gif


# ---------------------------------------------------------------------------
# GET /osint/{username}
# ---------------------------------------------------------------------------

class TestOsintLookup:
    def test_osint_no_results_on_http_error(self):
        with patch("main.requests.get", side_effect=Exception("network error")):
            resp = client.get("/osint/testuser", headers=auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "testuser"
        assert body["found_accounts"] == []

    def test_osint_github_found(self):
        github_resp = MagicMock()
        github_resp.status_code = 200

        reddit_resp = MagicMock()
        reddit_resp.status_code = 404

        with patch("main.requests.get", side_effect=[github_resp, Exception("reddit down")]):
            resp = client.get("/osint/octocat", headers=auth_headers())

        assert resp.status_code == 200
        body = resp.json()
        assert any(a["site"] == "GitHub" for a in body["found_accounts"])
