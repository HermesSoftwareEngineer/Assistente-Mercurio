"""Testes para os endpoints REST em app/api.py."""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def flask_app():
    sys.modules.pop("app.main", None)
    # Garante que constantes de módulo (ex: _OWNER_PHONE em handlers.py) sejam
    # populadas corretamente mesmo quando importadas pelo test suite.
    with patch("app.agent.scheduler.start_scheduler"):
        with patch.dict(os.environ, {"AUTHORIZED_NUMBER": "5585900000000"}):
            import app.main as _main
        _main.app.config["TESTING"] = True
        _main.app.config["SECRET_KEY"] = "test-secret-key"
        return _main.app


@pytest.fixture
def client(flask_app):
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def auth(client):
    with client.session_transaction() as sess:
        sess["authenticated"] = True
    return client


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

class TestAuthGuard:
    def test_tasks_requires_auth(self, client):
        r = client.get("/api/tasks")
        assert r.status_code == 401

    def test_groups_requires_auth(self, client):
        r = client.get("/api/groups")
        assert r.status_code == 401

    def test_books_requires_auth(self, client):
        r = client.get("/api/books")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

TASK = {
    "id": "uuid-1", "title": "Lembrete", "type": "reminder",
    "status": "pending", "payload": {"message": "Oi"}, "due_at": None,
    "contact_phone": None, "depends_on": [], "process_instance_id": None,
    "notes": None, "created_at": "2026-06-14T00:00:00+00:00",
    "updated_at": "2026-06-14T00:00:00+00:00", "completed_at": None,
    "timing_type": "immediate", "timing_value": None, "on_delay": "notify",
    "step_id": None,
}


class TestListTasks:
    def test_returns_task_list(self, auth):
        with patch("app.api._list_tasks", return_value=[TASK]) as m:
            r = auth.get("/api/tasks")
        assert r.status_code == 200
        body = r.get_json()
        assert body["count"] == 1
        assert body["tasks"][0]["id"] == "uuid-1"

    def test_passes_status_filter(self, auth):
        with patch("app.api._list_tasks", return_value=[]) as m:
            auth.get("/api/tasks?status=pending&type=reminder&limit=5&offset=10")
        m.assert_called_once_with(status="pending", type="reminder", limit=5, offset=10)

    def test_rejects_non_int_limit(self, auth):
        r = auth.get("/api/tasks?limit=abc")
        assert r.status_code == 400

    def test_empty_status_param_becomes_none(self, auth):
        with patch("app.api._list_tasks", return_value=[]) as m:
            auth.get("/api/tasks?status=")
        m.assert_called_once_with(status=None, type=None, limit=50, offset=0)


class TestCreateTask:
    def test_creates_and_returns_task(self, auth):
        with (
            patch("app.api._create_task", return_value="uuid-new"),
            patch("app.api._get_task", return_value={**TASK, "id": "uuid-new"}),
        ):
            r = auth.post("/api/tasks", json={
                "title": "Lembrete", "type": "reminder", "payload": {"message": "Oi"}
            })
        assert r.status_code == 201
        assert r.get_json()["id"] == "uuid-new"

    def test_requires_title(self, auth):
        r = auth.post("/api/tasks", json={"type": "reminder", "payload": {}})
        assert r.status_code == 400

    def test_requires_type(self, auth):
        r = auth.post("/api/tasks", json={"title": "Teste", "payload": {}})
        assert r.status_code == 400

    def test_rejects_invalid_type(self, auth):
        r = auth.post("/api/tasks", json={"title": "T", "type": "invalido", "payload": {}})
        assert r.status_code == 400

    def test_returns_500_on_db_error(self, auth):
        with patch("app.api._create_task", return_value=None):
            r = auth.post("/api/tasks", json={"title": "T", "type": "reminder", "payload": {}})
        assert r.status_code == 500


class TestGetTask:
    def test_returns_task(self, auth):
        with patch("app.api._get_task", return_value=TASK):
            r = auth.get("/api/tasks/uuid-1")
        assert r.status_code == 200
        assert r.get_json()["id"] == "uuid-1"

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api._get_task", return_value=None):
            r = auth.get("/api/tasks/no-exist")
        assert r.status_code == 404


class TestUpdateTask:
    def test_updates_status(self, auth):
        with (
            patch("app.api._get_task", return_value=TASK),
            patch("app.api._update_task", return_value=True),
        ):
            r = auth.patch("/api/tasks/uuid-1", json={"status": "done"})
        assert r.status_code == 200

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api._get_task", return_value=None):
            r = auth.patch("/api/tasks/no-exist", json={"status": "done"})
        assert r.status_code == 404

    def test_returns_400_with_no_fields(self, auth):
        with patch("app.api._get_task", return_value=TASK):
            r = auth.patch("/api/tasks/uuid-1", json={})
        assert r.status_code == 400


class TestCancelTask:
    def test_cancels_task(self, auth):
        with (
            patch("app.api._get_task", return_value=TASK),
            patch("app.api._cancel_task", return_value=True),
        ):
            r = auth.delete("/api/tasks/uuid-1")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_cascade_flag(self, auth):
        with (
            patch("app.api._get_task", return_value=TASK),
            patch("app.api._cancel_task", return_value=True) as m,
        ):
            auth.delete("/api/tasks/uuid-1?cascade=true")
        m.assert_called_once_with("uuid-1", cascade=True)

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api._get_task", return_value=None):
            r = auth.delete("/api/tasks/no-exist")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

class TestListProcesses:
    def test_returns_processes(self, auth):
        proc = {"id": "p1", "name": "coletar_roteiros", "active": True}
        with patch("app.api._list_processes", return_value=[proc]):
            r = auth.get("/api/processes")
        assert r.status_code == 200
        assert r.get_json()["processes"][0]["name"] == "coletar_roteiros"

    def test_active_only_default(self, auth):
        with patch("app.api._list_processes", return_value=[]) as m:
            auth.get("/api/processes")
        m.assert_called_once_with(active_only=True)

    def test_active_only_false(self, auth):
        with patch("app.api._list_processes", return_value=[]) as m:
            auth.get("/api/processes?active_only=false")
        m.assert_called_once_with(active_only=False)


class TestStartProcess:
    def test_starts_roteiro_collection(self, auth):
        result = {
            "instance_id": "inst-1",
            "collect_task_ids": ["t1", "t2"],
            "compile_task_id": "c1",
            "send_task_id": "s1",
            "notify_task_id": "n1",
            "error": None,
        }
        with patch("app.api.create_roteiro_collection", return_value=result):
            r = auth.post("/api/processes/start", json={
                "process_name": "coletar_roteiros",
                "parameters": {
                    "event_name": "Culto de Domingo",
                    "participants": [{"name": "João", "phone": "5585999990001"}],
                    "deadline": "2026-06-20T18:00:00-03:00",
                    "targets": ["Grupo Geral"],
                },
            })
        assert r.status_code == 201
        assert r.get_json()["instance_id"] == "inst-1"

    def test_returns_422_on_collection_error(self, auth):
        with patch("app.api.create_roteiro_collection", return_value={"error": "sem participantes"}):
            r = auth.post("/api/processes/start", json={
                "process_name": "coletar_roteiros",
                "parameters": {"participants": []},
            })
        assert r.status_code == 422

    def test_returns_400_without_process_name(self, auth):
        r = auth.post("/api/processes/start", json={"parameters": {}})
        assert r.status_code == 400

    def test_returns_404_for_unknown_process(self, auth):
        with patch("app.api.get_process_by_name", return_value=None):
            r = auth.post("/api/processes/start", json={
                "process_name": "processo_inexistente",
                "parameters": {},
            })
        assert r.status_code == 404


class TestListProcessInstances:
    def test_returns_instances(self, auth):
        inst = {"id": "inst-1", "process_name": "Coleta", "status": "in_progress"}
        with patch("app.api._list_process_instances", return_value=[inst]):
            r = auth.get("/api/process-instances")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["instances"][0]["id"] == "inst-1"

    def test_passes_status_filter(self, auth):
        with patch("app.api._list_process_instances", return_value=[]) as m:
            auth.get("/api/process-instances?status=done&limit=5")
        m.assert_called_once_with(status="done", limit=5)


class TestGetProcessInstance:
    def test_returns_instance_with_tasks(self, auth):
        inst = {"id": "inst-1", "process_name": "Coleta", "tasks": [TASK]}
        with patch("app.api._get_process_instance", return_value=inst):
            r = auth.get("/api/process-instances/inst-1")
        assert r.status_code == 200
        assert r.get_json()["tasks"][0]["id"] == "uuid-1"

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api._get_process_instance", return_value=None):
            r = auth.get("/api/process-instances/no-exist")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------

GROUP = {"id": "g1", "name": "Geral", "jid": "123@g.us", "category": "", "active": True}


class TestListGroups:
    def test_returns_groups(self, auth):
        with patch("app.api.get_groups", return_value=[GROUP]):
            r = auth.get("/api/groups")
        assert r.status_code == 200
        assert r.get_json()["groups"][0]["name"] == "Geral"


class TestAddGroup:
    def test_adds_group(self, auth):
        with patch("app.api.add_group", return_value=True):
            r = auth.post("/api/groups", json={"name": "Novo", "jid": "999@g.us"})
        assert r.status_code == 201
        assert r.get_json()["ok"] is True

    def test_requires_name_and_jid(self, auth):
        r = auth.post("/api/groups", json={"name": "Sem JID"})
        assert r.status_code == 400

    def test_returns_500_on_error(self, auth):
        with patch("app.api.add_group", return_value=False):
            r = auth.post("/api/groups", json={"name": "N", "jid": "j@g.us"})
        assert r.status_code == 500


class TestRemoveGroup:
    def test_removes_group(self, auth):
        with patch("app.api.remove_group", return_value=True):
            r = auth.delete("/api/groups/Geral")
        assert r.status_code == 200

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api.remove_group", return_value=False):
            r = auth.delete("/api/groups/Inexistente")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class TestListMessages:
    def test_returns_messages(self, auth):
        msg = {"id": "m1", "content": "Oi turma", "groups_sent": ["Geral"]}
        with patch("app.api.get_message_history", return_value=[msg]):
            r = auth.get("/api/messages")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["messages"][0]["content"] == "Oi turma"

    def test_passes_limit(self, auth):
        with patch("app.api.get_message_history", return_value=[]) as m:
            auth.get("/api/messages?limit=5")
        m.assert_called_once_with(limit=5)


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

class TestListBooks:
    def test_returns_books(self, auth):
        book = {"id": "b1", "title": "Bíblia", "pages": 1000, "chunks": 200}
        with patch("app.api._list_books", return_value=[book]):
            r = auth.get("/api/books")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["books"][0]["title"] == "Bíblia"


class TestDeleteBook:
    def test_deletes_book(self, auth):
        with patch("app.api._delete_book_by_id", return_value=True):
            r = auth.delete("/api/books/b1")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True

    def test_returns_404_when_not_found(self, auth):
        with patch("app.api._delete_book_by_id", return_value=False):
            r = auth.delete("/api/books/no-exist")
        assert r.status_code == 404
