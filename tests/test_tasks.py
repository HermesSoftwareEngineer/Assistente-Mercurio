"""Testes unitários para app/services/tasks.py (sem conexão real ao Supabase)."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers para construir mocks do cliente Supabase
# ---------------------------------------------------------------------------

def _make_client(data=None, *, side_effect=None):
    """Retorna um mock de get_client() que responde com `data` em .execute().data."""
    client = MagicMock()
    execute = MagicMock()
    execute.data = data if data is not None else []
    if side_effect:
        execute.side_effect = side_effect
    # Encadeia todos os métodos do query builder de volta para chain
    chain = MagicMock()
    chain.execute.return_value = execute
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.delete.return_value = chain
    chain.eq.return_value = chain
    chain.in_.return_value = chain
    chain.not_.return_value = chain
    chain.lte.return_value = chain
    chain.gte.return_value = chain
    chain.lt.return_value = chain
    chain.contains.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    client.table.return_value = chain
    return client


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

class TestCreateTask:
    def test_creates_task_without_depends_on(self):
        data = [{"id": "abc-123"}]
        with patch("app.services.tasks.get_client", return_value=_make_client(data)):
            from app.services.tasks import create_task
            result = create_task("Lembrete teste", "reminder", {"message": "Oi"})
        assert result == "abc-123"

    def test_returns_none_on_empty_data(self):
        with patch("app.services.tasks.get_client", return_value=_make_client([])):
            from app.services.tasks import create_task
            result = create_task("X", "reminder", {})
        assert result is None

    def test_status_blocked_when_has_depends_on(self):
        client = _make_client([{"id": "xyz"}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import create_task
            create_task("Task dependente", "wait", {}, depends_on=["parent-id"])
        # Verifica que insert foi chamado com status=blocked
        insert_call = client.table.return_value.insert.call_args
        assert insert_call is not None
        row = insert_call[0][0]
        assert row["status"] == "blocked"
        assert row["depends_on"] == ["parent-id"]

    def test_status_pending_without_depends_on(self):
        client = _make_client([{"id": "xyz"}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import create_task
            create_task("Task simples", "reminder", {})
        insert_call = client.table.return_value.insert.call_args
        row = insert_call[0][0]
        assert row["status"] == "pending"

    def test_returns_none_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import create_task
            result = create_task("X", "reminder", {})
        assert result is None


# ---------------------------------------------------------------------------
# get_task
# ---------------------------------------------------------------------------

class TestGetTask:
    def test_returns_task_when_found(self):
        task = {"id": "task-1", "title": "Teste", "status": "pending"}
        with patch("app.services.tasks.get_client", return_value=_make_client([task])):
            from app.services.tasks import get_task
            result = get_task("task-1")
        assert result == task

    def test_returns_none_when_not_found(self):
        with patch("app.services.tasks.get_client", return_value=_make_client([])):
            from app.services.tasks import get_task
            result = get_task("inexistente")
        assert result is None

    def test_returns_none_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import get_task
            result = get_task("task-1")
        assert result is None


# ---------------------------------------------------------------------------
# update_task
# ---------------------------------------------------------------------------

class TestUpdateTask:
    def test_updates_status(self):
        client = _make_client([{"id": "t1", "payload": {}}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import update_task
            result = update_task("t1", status="done")
        assert result is True

    def test_sets_completed_at_when_done(self):
        client = _make_client([{"id": "t1", "payload": {}}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import update_task
            update_task("t1", status="done")
        update_call = client.table.return_value.update.call_args
        updates = update_call[0][0]
        assert "completed_at" in updates

    def test_does_not_set_completed_at_for_other_statuses(self):
        client = _make_client([{"id": "t1", "payload": {}}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import update_task
            update_task("t1", status="cancelled")
        update_call = client.table.return_value.update.call_args
        updates = update_call[0][0]
        assert "completed_at" not in updates

    def test_merges_payload_patch(self):
        existing_payload = {"message": "original", "retry_count": 0}
        # Primeiro get_task retorna payload existente, segundo é o update
        client = MagicMock()
        execute_select = MagicMock()
        execute_select.data = [{"id": "t1", "payload": existing_payload}]
        execute_update = MagicMock()
        execute_update.data = [{"id": "t1"}]

        chain = MagicMock()
        chain.execute.side_effect = [execute_select, execute_update]
        chain.eq.return_value = chain
        chain.limit.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        client.table.return_value = chain

        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import update_task
            update_task("t1", payload_patch={"retry_count": 1})

        update_call = chain.update.call_args
        merged = update_call[0][0]["payload"]
        assert merged["message"] == "original"
        assert merged["retry_count"] == 1

    def test_returns_false_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import update_task
            result = update_task("t1", status="done")
        assert result is False


# ---------------------------------------------------------------------------
# cancel_task
# ---------------------------------------------------------------------------

class TestCancelTask:
    def test_cancels_task(self):
        client = _make_client([{"id": "t1"}])
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import cancel_task
            result = cancel_task("t1")
        assert result is True

    def test_returns_false_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import cancel_task
            result = cancel_task("t1")
        assert result is False


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------

class TestListTasks:
    def test_returns_all_tasks_without_filter(self):
        tasks = [{"id": "1"}, {"id": "2"}]
        with patch("app.services.tasks.get_client", return_value=_make_client(tasks)):
            from app.services.tasks import list_tasks
            result = list_tasks()
        assert len(result) == 2

    def test_returns_empty_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import list_tasks
            result = list_tasks()
        assert result == []


# ---------------------------------------------------------------------------
# get_pending_due_tasks
# ---------------------------------------------------------------------------

class TestGetPendingDueTasks:
    def test_returns_due_tasks(self):
        tasks = [{"id": "t1", "status": "pending"}]
        with patch("app.services.tasks.get_client", return_value=_make_client(tasks)):
            from app.services.tasks import get_pending_due_tasks
            result = get_pending_due_tasks()
        assert result == tasks

    def test_returns_empty_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import get_pending_due_tasks
            result = get_pending_due_tasks()
        assert result == []


# ---------------------------------------------------------------------------
# get_active_tasks_for_phone
# ---------------------------------------------------------------------------

class TestGetActiveTasksForPhone:
    def test_returns_tasks_for_phone(self):
        tasks = [{"id": "t1", "contact_phone": "5585999990000", "type": "collect_from_contact"}]
        with patch("app.services.tasks.get_client", return_value=_make_client(tasks)):
            from app.services.tasks import get_active_tasks_for_phone
            result = get_active_tasks_for_phone("5585999990000")
        assert result == tasks

    def test_returns_empty_when_no_active_tasks(self):
        with patch("app.services.tasks.get_client", return_value=_make_client([])):
            from app.services.tasks import get_active_tasks_for_phone
            result = get_active_tasks_for_phone("5585999990000")
        assert result == []


# ---------------------------------------------------------------------------
# unblock_dependents
# ---------------------------------------------------------------------------

class TestUnblockDependents:
    def test_unblocks_task_when_all_deps_done(self):
        # blocked task que depende de "completed-id"
        blocked_task = {"id": "blocked-1", "depends_on": ["completed-id"]}
        # Segunda consulta: a dependência está done
        done_dep = [{"id": "completed-id"}]

        client = MagicMock()
        ex1 = MagicMock(); ex1.data = [blocked_task]
        ex2 = MagicMock(); ex2.data = done_dep
        ex3 = MagicMock(); ex3.data = []

        chain = MagicMock()
        chain.execute.side_effect = [ex1, ex2, ex3]
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.contains.return_value = chain
        chain.select.return_value = chain
        chain.update.return_value = chain
        client.table.return_value = chain

        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import unblock_dependents
            unblocked = unblock_dependents("completed-id")

        assert "blocked-1" in unblocked

    def test_does_not_unblock_when_other_dep_not_done(self):
        # blocked task que depende de 2 tasks — a segunda ainda não está done
        blocked_task = {"id": "blocked-1", "depends_on": ["completed-id", "pending-id"]}
        # done_deps retorna só 1 dos 2
        done_deps = [{"id": "completed-id"}]

        client = MagicMock()
        ex1 = MagicMock(); ex1.data = [blocked_task]
        ex2 = MagicMock(); ex2.data = done_deps

        chain = MagicMock()
        chain.execute.side_effect = [ex1, ex2]
        chain.eq.return_value = chain
        chain.in_.return_value = chain
        chain.contains.return_value = chain
        chain.select.return_value = chain
        client.table.return_value = chain

        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import unblock_dependents
            unblocked = unblock_dependents("completed-id")

        assert unblocked == []

    def test_returns_empty_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import unblock_dependents
            result = unblock_dependents("any-id")
        assert result == []


# ---------------------------------------------------------------------------
# get_late_tasks_at_startup
# ---------------------------------------------------------------------------

class TestGetLateTasksAtStartup:
    def test_separates_execute_and_notify(self):
        execute_tasks = [{"id": "recent"}]
        notify_tasks = [{"id": "old"}]

        client = MagicMock()
        ex_recent = MagicMock(); ex_recent.data = execute_tasks
        ex_old = MagicMock(); ex_old.data = notify_tasks

        chain = MagicMock()
        chain.execute.side_effect = [ex_recent, ex_old]
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.lt.return_value = chain
        chain.select.return_value = chain
        client.table.return_value = chain

        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import get_late_tasks_at_startup
            result = get_late_tasks_at_startup(cutoff_hours=48)

        assert result["execute"] == execute_tasks
        assert result["notify"] == notify_tasks

    def test_returns_empty_dicts_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.tasks.get_client", return_value=client):
            from app.services.tasks import get_late_tasks_at_startup
            result = get_late_tasks_at_startup()
        assert result == {"execute": [], "notify": []}
