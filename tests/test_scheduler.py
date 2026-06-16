"""Testes unitários para app/agent/scheduler.py."""
import os
import pytest
from unittest.mock import patch, MagicMock, call


OWNER = "5585900000000"

# ---------------------------------------------------------------------------
# _all_dependencies_done
# ---------------------------------------------------------------------------

class TestAllDependenciesDone:
    def test_returns_true_when_all_done(self):
        done_task = {"id": "dep-1", "status": "done"}
        with patch("app.services.tasks.get_task", return_value=done_task):
            from app.agent.scheduler import _all_dependencies_done
            assert _all_dependencies_done(["dep-1"]) is True

    def test_returns_false_when_dep_not_done(self):
        pending_task = {"id": "dep-1", "status": "pending"}
        with patch("app.services.tasks.get_task", return_value=pending_task):
            from app.agent.scheduler import _all_dependencies_done
            assert _all_dependencies_done(["dep-1"]) is False

    def test_returns_false_when_dep_not_found(self):
        with patch("app.services.tasks.get_task", return_value=None):
            from app.agent.scheduler import _all_dependencies_done
            assert _all_dependencies_done(["missing-id"]) is False

    def test_returns_true_for_empty_list(self):
        from app.agent.scheduler import _all_dependencies_done
        assert _all_dependencies_done([]) is True

    def test_returns_false_when_any_dep_not_done(self):
        tasks = {
            "dep-done": {"id": "dep-done", "status": "done"},
            "dep-pending": {"id": "dep-pending", "status": "pending"},
        }
        with patch("app.services.tasks.get_task", side_effect=lambda tid: tasks.get(tid)):
            from app.agent.scheduler import _all_dependencies_done
            assert _all_dependencies_done(["dep-done", "dep-pending"]) is False


# ---------------------------------------------------------------------------
# _notify_hermes_missed
# ---------------------------------------------------------------------------

class TestNotifyHermesMissed:
    def test_sends_message_with_task_info(self):
        task = {"id": "task-001", "title": "Enviar aviso", "due_at": "2026-06-13T10:00:00"}
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _notify_hermes_missed
            _notify_hermes_missed(task)

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Enviar aviso" in msg
        assert "48h" in msg or "offline" in msg
        assert "task-001" in msg

    def test_uses_owner_phone(self):
        task = {"id": "t1", "title": "Teste", "due_at": "2026-06-13T10:00:00"}
        # _OWNER_PHONE é constante de módulo — precisa de patch direto
        with (
            patch("app.agent.scheduler._OWNER_PHONE", OWNER),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _notify_hermes_missed
            _notify_hermes_missed(task)
        assert mock_send.call_args[0][0] == OWNER


# ---------------------------------------------------------------------------
# _notify_hermes_overdue
# ---------------------------------------------------------------------------

class TestNotifyHermesOverdue:
    def test_sends_message_with_task_details(self):
        task = {
            "id": "task-002",
            "title": "Coletar rotário",
            "type": "collect_from_contact",
            "due_at": "2026-06-14T18:00:00",
        }
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _notify_hermes_overdue
            _notify_hermes_overdue(task)

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Coletar rotário" in msg
        assert "task-002" in msg


# ---------------------------------------------------------------------------
# _notify_hermes_failed
# ---------------------------------------------------------------------------

class TestNotifyHermesFailed:
    def test_sends_failure_message(self):
        task = {"id": "task-003", "title": "Enviar no grupo", "type": "send_message"}
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _notify_hermes_failed
            _notify_hermes_failed(task)

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Enviar no grupo" in msg
        assert "❌" in msg or "Falha" in msg or "falha" in msg


# ---------------------------------------------------------------------------
# _run_task
# ---------------------------------------------------------------------------

class TestRunTask:
    def test_marks_done_on_success(self):
        task = {"id": "t1", "title": "Lembrete", "type": "reminder", "payload": {"message": "Oi"}}
        with (
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
            patch("app.services.tasks.unblock_dependents", return_value=[]),
            patch("app.agent.handlers.dispatch_handler", return_value=True),
            patch("app.agent.scheduler.dispatch_handler", return_value=True),
        ):
            from app.agent.scheduler import _run_task
            _run_task(task)

        statuses = [c[1].get("status") or c[0][1] for c in mock_update.call_args_list
                    if mock_update.call_args_list]
        calls_kwargs = [c.kwargs for c in mock_update.call_args_list]
        statuses_set = {kw.get("status") for kw in calls_kwargs}
        assert "in_progress" in statuses_set
        assert "done" in statuses_set

    def test_marks_failed_on_handler_error(self):
        task = {"id": "t2", "title": "Tarefa", "type": "send_message", "payload": {}}
        with (
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
            patch("app.agent.scheduler.dispatch_handler", return_value=False),
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message"),
        ):
            from app.agent.scheduler import _run_task
            _run_task(task)

        calls_kwargs = [c.kwargs for c in mock_update.call_args_list]
        statuses_set = {kw.get("status") for kw in calls_kwargs}
        assert "failed" in statuses_set

    def test_notifies_hermes_on_failure(self):
        task = {"id": "t3", "title": "Falha", "type": "send_message", "payload": {}}
        with (
            patch("app.services.tasks.update_task", return_value=True),
            patch("app.agent.scheduler.dispatch_handler", return_value=False),
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _run_task
            _run_task(task)
        assert mock_send.called


# ---------------------------------------------------------------------------
# _check_late_tasks_at_startup
# ---------------------------------------------------------------------------

class TestCheckLateTasksAtStartup:
    def test_executes_recent_late_tasks(self):
        recent_task = {"id": "r1", "title": "Recente", "type": "reminder",
                       "payload": {"message": "Oi"}, "depends_on": []}
        late_data = {"execute": [recent_task], "notify": []}

        with (
            patch("app.services.tasks.get_late_tasks_at_startup", return_value=late_data),
            patch("app.services.tasks.update_task", return_value=True),
            patch("app.services.tasks.unblock_dependents", return_value=[]),
            patch("app.agent.scheduler.dispatch_handler", return_value=True),
        ):
            from app.agent.scheduler import _check_late_tasks_at_startup
            _check_late_tasks_at_startup()

    def test_notifies_and_marks_missed_for_old_tasks(self):
        old_task = {"id": "o1", "title": "Antiga", "type": "reminder",
                    "payload": {"message": "Velho"}, "due_at": "2026-06-01T10:00:00"}
        late_data = {"execute": [], "notify": [old_task]}

        with (
            patch("app.services.tasks.get_late_tasks_at_startup", return_value=late_data),
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.scheduler.send_message") as mock_send,
        ):
            from app.agent.scheduler import _check_late_tasks_at_startup
            _check_late_tasks_at_startup()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Antiga" in msg

        mock_update.assert_called_once_with("o1", status="missed")


# ---------------------------------------------------------------------------
# _run_task — retorno None (in_progress)
# ---------------------------------------------------------------------------

class TestRunTaskNoneReturn:
    def test_does_not_change_status_when_handler_returns_none(self):
        task = {"id": "t-collect", "title": "Cobrar João", "type": "collect_from_contact",
                "payload": {"message": "Oi"}, "contact_phone": "5585999990001", "depends_on": []}
        with (
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
            patch("app.services.tasks.unblock_dependents", return_value=[]),
            patch("app.agent.scheduler.dispatch_handler", return_value=None),
        ):
            from app.agent.scheduler import _run_task
            _run_task(task)

        statuses = [c.kwargs.get("status") for c in mock_update.call_args_list]
        # Deve ter marcado in_progress, mas NÃO done nem failed
        assert "in_progress" in statuses
        assert "done" not in statuses
        assert "failed" not in statuses


# ---------------------------------------------------------------------------
# _retry_collect_task
# ---------------------------------------------------------------------------

class TestRetryCollectTask:
    def _collect_task(self, retry_count=0, max_retries=3, task_type="collect_from_contact"):
        return {
            "id": "task-retry-001",
            "title": "Cobrar João sobre rotário",
            "type": task_type,
            "contact_phone": "5585999990001",
            "payload": {
                "message": "Oi João, rotário?",
                "retry_message": "João, ainda aguardando seu rotário!",
                "retry_interval_hours": 1,
                "max_retries": max_retries,
                "retry_count": retry_count,
            },
        }

    def test_sends_retry_message_when_under_max(self):
        task = self._collect_task(retry_count=1, max_retries=3)
        with (
            patch("app.agent.scheduler._OWNER_PHONE", OWNER),
            patch("app.agent.scheduler.send_message", return_value=True) as mock_send,
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
        ):
            from app.agent.scheduler import _retry_collect_task
            _retry_collect_task(task)

        # Deve ter enviado retry_message para o contato
        mock_send.assert_called_once_with("5585999990001", "João, ainda aguardando seu rotário!")
        # Deve ter incrementado retry_count
        update_calls = [c for c in mock_update.call_args_list]
        payload_patches = [c.kwargs.get("payload_patch", {}) for c in update_calls]
        assert any(p.get("retry_count") == 2 for p in payload_patches)

    def test_notifies_hermes_and_marks_done_when_max_retries_reached(self):
        task = self._collect_task(retry_count=3, max_retries=3)
        with (
            patch("app.agent.scheduler._OWNER_PHONE", OWNER),
            patch("app.agent.scheduler.send_message") as mock_send,
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
        ):
            from app.agent.scheduler import _retry_collect_task
            _retry_collect_task(task)

        # Deve ter notificado Hermes sobre max retries
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "3" in msg  # max_retries no texto

        # Deve ter marcado como done
        statuses = [c.kwargs.get("status") for c in mock_update.call_args_list]
        assert "done" in statuses

    def test_ask_hermes_retry_resends_to_owner(self):
        task = self._collect_task(retry_count=0, max_retries=3, task_type="ask_hermes")
        task["contact_phone"] = OWNER
        task["payload"]["question"] = "Quem participa do culto?"
        with (
            patch("app.agent.scheduler._OWNER_PHONE", OWNER),
            patch("app.agent.scheduler.send_message", return_value=True) as mock_send,
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.scheduler import _retry_collect_task
            _retry_collect_task(task)

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Quem participa do culto?" in msg

    def test_reschedules_due_at_after_retry(self):
        task = self._collect_task(retry_count=0, max_retries=3)
        with (
            patch("app.agent.scheduler._OWNER_PHONE", OWNER),
            patch("app.agent.scheduler.send_message", return_value=True),
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
        ):
            from app.agent.scheduler import _retry_collect_task
            _retry_collect_task(task)

        update_calls = [c for c in mock_update.call_args_list]
        due_ats = [c.kwargs.get("due_at") for c in update_calls if c.kwargs.get("due_at")]
        assert len(due_ats) == 1  # deve ter reagendado


# ---------------------------------------------------------------------------
# start_scheduler / stop_scheduler
# ---------------------------------------------------------------------------

class TestSchedulerLifecycle:
    def test_start_and_stop(self):
        with patch("app.agent.scheduler._check_late_tasks_at_startup"):
            from app.agent.scheduler import start_scheduler, stop_scheduler, _scheduler as sched_before
            start_scheduler()
            from app.agent.scheduler import _scheduler
            assert _scheduler is not None
            assert _scheduler.running
            stop_scheduler()
            assert not _scheduler.running

    def test_double_start_is_idempotent(self):
        with patch("app.agent.scheduler._check_late_tasks_at_startup"):
            from app.agent.scheduler import start_scheduler, stop_scheduler
            start_scheduler()
            start_scheduler()  # segunda chamada deve ser ignorada
            from app.agent.scheduler import _scheduler
            assert _scheduler.running
            stop_scheduler()
