"""Testes unitários para app/services/processes.py."""
import pytest
from unittest.mock import MagicMock, patch, call


def _make_client(data=None):
    client = MagicMock()
    execute = MagicMock()
    execute.data = data if data is not None else []
    chain = MagicMock()
    chain.execute.return_value = execute
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.ilike.return_value = chain
    chain.order.return_value = chain
    chain.limit.return_value = chain
    client.table.return_value = chain
    return client


# ---------------------------------------------------------------------------
# create_process_instance
# ---------------------------------------------------------------------------

class TestCreateProcessInstance:
    def test_creates_instance_and_returns_id(self):
        client = _make_client([{"id": "inst-001"}])
        with patch("app.services.processes.get_client", return_value=client):
            from app.services.processes import create_process_instance
            result = create_process_instance("Coleta de Roteiros — Culto", {"event_name": "Culto"})
        assert result == "inst-001"

    def test_returns_none_when_no_data(self):
        client = _make_client([])
        with patch("app.services.processes.get_client", return_value=client):
            from app.services.processes import create_process_instance
            result = create_process_instance("X", {})
        assert result is None

    def test_returns_none_on_exception(self):
        client = MagicMock()
        client.table.side_effect = Exception("DB error")
        with patch("app.services.processes.get_client", return_value=client):
            from app.services.processes import create_process_instance
            result = create_process_instance("X", {})
        assert result is None


# ---------------------------------------------------------------------------
# create_roteiro_collection
# ---------------------------------------------------------------------------

PARTICIPANTS = [
    {"name": "João", "phone": "5585111111111"},
    {"name": "Maria", "phone": "5585222222222"},
]

class TestCreateRoteiroCollection:
    def _patch_create_task(self, id_gen=None):
        """Patch create_task para retornar IDs sequenciais."""
        counter = [0]
        def gen(*args, **kwargs):
            counter[0] += 1
            return id_gen[counter[0] - 1] if id_gen else f"task-{counter[0]:03d}"
        return gen

    def test_creates_collect_tasks_for_each_participant(self):
        ids = ["collect-1", "collect-2", "compile-1", "send-1", "notify-1"]
        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "inst-1"}])),
            patch("app.services.tasks.get_client", return_value=_make_client([{"id": "x"}])),
            patch("app.services.processes.create_task", side_effect=self._patch_create_task(ids)) as mock_ct,
        ):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto de Domingo",
                participants=PARTICIPANTS,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )
        assert len(result["collect_task_ids"]) == 2
        assert result["error"] is None

    def test_creates_compile_task_depending_on_collects(self):
        collect_ids = ["c1", "c2"]
        all_ids = collect_ids + ["compile-1", "send-1", "notify-1"]
        created_tasks = []

        def capture_create(*args, **kwargs):
            idx = len(created_tasks)
            task_id = all_ids[idx] if idx < len(all_ids) else f"extra-{idx}"
            created_tasks.append(kwargs)
            return task_id

        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "inst-1"}])),
            patch("app.services.processes.create_task", side_effect=capture_create),
        ):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto",
                participants=PARTICIPANTS,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )

        # A 3ª task criada (índice 2) é a compile
        compile_kwargs = created_tasks[2]
        assert compile_kwargs.get("type") == "compile"
        assert set(collect_ids) == set(compile_kwargs.get("depends_on", []))

    def test_creates_send_and_notify_tasks(self):
        all_ids = ["c1", "c2", "compile-1", "send-1", "notify-1"]
        counter = [0]
        def gen(**kwargs):
            idx = counter[0]
            counter[0] += 1
            return all_ids[idx] if idx < len(all_ids) else None

        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "inst-1"}])),
            patch("app.services.processes.create_task", side_effect=gen),
        ):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto",
                participants=PARTICIPANTS,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )
        assert result["compile_task_id"] == "compile-1"
        assert result["send_task_id"] == "send-1"
        assert result["notify_task_id"] == "notify-1"

    def test_returns_error_when_no_participants(self):
        with patch("app.services.processes.get_client", return_value=_make_client([{"id": "i"}])):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto",
                participants=[],
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )
        assert result["error"] is not None

    def test_skips_participants_without_phone(self):
        participants = [
            {"name": "João", "phone": "5585111111111"},
            {"name": "Maria", "phone": ""},  # sem telefone
        ]
        counter = [0]
        ids = ["c1", "compile-1", "send-1", "notify-1"]
        def gen(**kwargs):
            idx = counter[0]; counter[0] += 1
            return ids[idx] if idx < len(ids) else None

        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "i"}])),
            patch("app.services.processes.create_task", side_effect=gen),
        ):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto",
                participants=participants,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )
        assert len(result["collect_task_ids"]) == 1  # só João

    def test_uses_message_template(self):
        created_payloads = []
        counter = [0]
        ids = ["c1", "c2", "compile-1", "send-1", "notify-1"]
        def capture(**kwargs):
            created_payloads.append(kwargs.get("payload", {}))
            idx = counter[0]; counter[0] += 1
            return ids[idx] if idx < len(ids) else None

        template = "Olá {name}, roteiro do {event_name} por favor!"
        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "i"}])),
            patch("app.services.processes.create_task", side_effect=capture),
        ):
            from app.services.processes import create_roteiro_collection
            create_roteiro_collection(
                event_name="Culto",
                participants=PARTICIPANTS,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
                message_template=template,
            )
        # Primeiro payload é de collect_from_contact para João
        first_msg = created_payloads[0].get("message", "")
        assert "João" in first_msg and "Culto" in first_msg

    def test_returns_error_when_all_phones_missing(self):
        participants = [{"name": "João", "phone": ""}, {"name": "Maria", "phone": ""}]
        with (
            patch("app.services.processes.get_client", return_value=_make_client([{"id": "i"}])),
            patch("app.services.processes.create_task", return_value="x"),
        ):
            from app.services.processes import create_roteiro_collection
            result = create_roteiro_collection(
                event_name="Culto",
                participants=participants,
                deadline="2026-06-21T18:00:00-03:00",
                targets=["Jovens"],
            )
        assert result["error"] is not None
        assert result["collect_task_ids"] == []
