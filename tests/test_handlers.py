"""Testes unitários para app/agent/handlers.py."""
import os
import pytest
from unittest.mock import patch, MagicMock


OWNER = "5585900000000"


def _task(type: str, payload: dict, **kwargs) -> dict:
    return {"id": "task-uuid-001", "type": type, "payload": payload, **kwargs}


# ---------------------------------------------------------------------------
# reminder_handler
# ---------------------------------------------------------------------------

class TestReminderHandler:
    def test_sends_message_to_owner(self):
        task = _task("reminder", {"message": "Hora de checar os avisos"})
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=True) as mock_send,
        ):
            from app.agent.handlers import reminder_handler
            result = reminder_handler(task)
        mock_send.assert_called_once_with(OWNER, "Hora de checar os avisos")
        assert result is True

    def test_returns_false_when_no_message(self):
        task = _task("reminder", {})
        with patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}):
            from app.agent.handlers import reminder_handler
            result = reminder_handler(task)
        assert result is False

    def test_returns_false_when_send_fails(self):
        task = _task("reminder", {"message": "Lembrete"})
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=False),
        ):
            from app.agent.handlers import reminder_handler
            result = reminder_handler(task)
        assert result is False


# ---------------------------------------------------------------------------
# notify_hermes_handler
# ---------------------------------------------------------------------------

class TestNotifyHermesHandler:
    def test_sends_message_to_owner(self):
        task = _task("notify_hermes", {"message": "Tarefa concluída"})
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=True) as mock_send,
        ):
            from app.agent.handlers import notify_hermes_handler
            result = notify_hermes_handler(task)
        mock_send.assert_called_once_with(OWNER, "Tarefa concluída")
        assert result is True

    def test_returns_false_when_no_message(self):
        task = _task("notify_hermes", {})
        with patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}):
            from app.agent.handlers import notify_hermes_handler
            result = notify_hermes_handler(task)
        assert result is False


# ---------------------------------------------------------------------------
# send_message_handler — grupos
# ---------------------------------------------------------------------------

class TestSendMessageHandlerGroups:
    def test_sends_to_group_by_name(self):
        task = _task("send_message", {
            "content": "Aviso do culto",
            "target_type": "group",
            "targets": ["Jovens"],
        })
        group = {"name": "Jovens", "jid": "12345@g.us"}
        with (
            patch("app.agent.handlers.get_group_by_name", return_value=group),
            patch("app.agent.handlers.send_group_message", return_value=True) as mock_send,
        ):
            from app.agent.handlers import send_message_handler
            result = send_message_handler(task)
        mock_send.assert_called_once_with("12345@g.us", "Aviso do culto")
        assert result is True

    def test_fails_gracefully_when_group_not_found(self):
        task = _task("send_message", {
            "content": "Aviso",
            "target_type": "group",
            "targets": ["GrupoInexistente"],
        })
        with patch("app.agent.handlers.get_group_by_name", return_value=None):
            from app.agent.handlers import send_message_handler
            result = send_message_handler(task)
        assert result is False

    def test_sends_to_multiple_groups(self):
        task = _task("send_message", {
            "content": "Aviso geral",
            "target_type": "group",
            "targets": ["Jovens", "Sede"],
        })
        groups = {"Jovens": {"jid": "111@g.us"}, "Sede": {"jid": "222@g.us"}}
        with (
            patch("app.agent.handlers.get_group_by_name", side_effect=lambda n: groups.get(n)),
            patch("app.agent.handlers.send_group_message", return_value=True) as mock_send,
        ):
            from app.agent.handlers import send_message_handler
            result = send_message_handler(task)
        assert mock_send.call_count == 2
        assert result is True


# ---------------------------------------------------------------------------
# send_message_handler — direto
# ---------------------------------------------------------------------------

class TestSendMessageHandlerDirect:
    def test_sends_direct_message(self):
        task = _task("send_message", {
            "content": "Olá João",
            "target_type": "direct",
            "targets": ["5585999990001"],
        })
        with patch("app.agent.handlers.send_message", return_value=True) as mock_send:
            from app.agent.handlers import send_message_handler
            result = send_message_handler(task)
        mock_send.assert_called_once_with("5585999990001", "Olá João")
        assert result is True

    def test_returns_false_without_content(self):
        task = _task("send_message", {"target_type": "direct", "targets": ["5585999990001"]})
        from app.agent.handlers import send_message_handler
        result = send_message_handler(task)
        assert result is False

    def test_returns_false_without_targets(self):
        task = _task("send_message", {"content": "Olá", "target_type": "direct", "targets": []})
        from app.agent.handlers import send_message_handler
        result = send_message_handler(task)
        assert result is False


# ---------------------------------------------------------------------------
# wait_handler
# ---------------------------------------------------------------------------

class TestWaitHandler:
    def test_always_returns_true(self):
        task = _task("wait", {"reason": "Aguardando horário"})
        from app.agent.handlers import wait_handler
        assert wait_handler(task) is True

    def test_returns_true_with_empty_payload(self):
        task = _task("wait", {})
        from app.agent.handlers import wait_handler
        assert wait_handler(task) is True


# ---------------------------------------------------------------------------
# dispatch_handler
# ---------------------------------------------------------------------------

class TestDispatchHandler:
    def test_dispatches_reminder(self):
        task = _task("reminder", {"message": "Lembrete"})
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=True),
        ):
            from app.agent.handlers import dispatch_handler
            result = dispatch_handler(task)
        assert result is True

    def test_dispatches_notify_hermes(self):
        task = _task("notify_hermes", {"message": "Status"})
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=True),
        ):
            from app.agent.handlers import dispatch_handler
            result = dispatch_handler(task)
        assert result is True

    def test_dispatches_wait(self):
        task = _task("wait", {})
        from app.agent.handlers import dispatch_handler
        assert dispatch_handler(task) is True

    def test_returns_false_for_unimplemented_types(self):
        # Tipos que ainda não existem retornam False
        task = _task("tipo_que_nao_existe_fase99", {})
        from app.agent.handlers import dispatch_handler
        assert dispatch_handler(task) is False

    def test_dispatches_collect_from_contact_returns_none_on_success(self):
        task = _task("collect_from_contact", {
            "message": "Oi João, pode me enviar o rotário?",
            "retry_interval_hours": 1,
            "max_retries": 3,
            "retry_count": 0,
        }, contact_phone="5585999990001")
        with (
            patch("app.agent.handlers.send_message", return_value=True),
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.handlers import dispatch_handler
            result = dispatch_handler(task)
        assert result is None

    def test_dispatches_ask_hermes_returns_none_on_success(self):
        task = _task("ask_hermes", {"question": "Quem vai participar do culto?"}, contact_phone=OWNER)
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers.send_message", return_value=True),
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.handlers import dispatch_handler
            result = dispatch_handler(task)
        assert result is None

    def test_returns_false_for_unknown_type(self):
        task = _task("tipo_invalido", {})
        from app.agent.handlers import dispatch_handler
        assert dispatch_handler(task) is False


# ---------------------------------------------------------------------------
# collect_from_contact_handler
# ---------------------------------------------------------------------------

class TestCollectFromContactHandler:
    def test_sends_message_and_returns_none(self):
        task = _task("collect_from_contact", {
            "message": "Oi João, pode me enviar o rotário?",
            "retry_interval_hours": 1,
            "max_retries": 3,
            "retry_count": 0,
        }, contact_phone="5585999990001")
        with (
            patch("app.agent.handlers.send_message", return_value=True) as mock_send,
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.handlers import collect_from_contact_handler
            result = collect_from_contact_handler(task)
        mock_send.assert_called_once_with("5585999990001", "Oi João, pode me enviar o rotário?")
        assert result is None

    def test_returns_false_when_no_contact_phone(self):
        task = _task("collect_from_contact", {"message": "Oi"})
        from app.agent.handlers import collect_from_contact_handler
        assert collect_from_contact_handler(task) is False

    def test_returns_false_when_no_message(self):
        task = _task("collect_from_contact", {}, contact_phone="5585999990001")
        from app.agent.handlers import collect_from_contact_handler
        assert collect_from_contact_handler(task) is False

    def test_returns_false_when_send_fails(self):
        task = _task("collect_from_contact", {
            "message": "Oi João",
            "retry_interval_hours": 1,
        }, contact_phone="5585999990001")
        with patch("app.agent.handlers.send_message", return_value=False):
            from app.agent.handlers import collect_from_contact_handler
            assert collect_from_contact_handler(task) is False

    def test_schedules_retry_via_due_at(self):
        task = _task("collect_from_contact", {
            "message": "Oi",
            "retry_interval_hours": 2,
            "max_retries": 3,
            "retry_count": 0,
        }, contact_phone="5585999990001")
        with (
            patch("app.agent.handlers.send_message", return_value=True),
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
        ):
            from app.agent.handlers import collect_from_contact_handler
            collect_from_contact_handler(task)
        # Verifica que update_task foi chamado com um due_at (reagendamento)
        mock_update.assert_called_once()
        kwargs = mock_update.call_args.kwargs
        assert "due_at" in kwargs


# ---------------------------------------------------------------------------
# ask_hermes_handler
# ---------------------------------------------------------------------------

class TestAskHermesHandler:
    def test_sends_question_to_owner_and_returns_none(self):
        task = _task("ask_hermes", {"question": "Quem vai participar do culto?"}, contact_phone=OWNER)
        with (
            patch.dict(os.environ, {"AUTHORIZED_NUMBER": OWNER}),
            patch("app.agent.handlers._OWNER_PHONE", OWNER),
            patch("app.agent.handlers.send_message", return_value=True) as mock_send,
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.handlers import ask_hermes_handler
            result = ask_hermes_handler(task)
        mock_send.assert_called_once_with(OWNER, "Quem vai participar do culto?")
        assert result is None

    def test_returns_false_when_no_question(self):
        task = _task("ask_hermes", {}, contact_phone=OWNER)
        from app.agent.handlers import ask_hermes_handler
        assert ask_hermes_handler(task) is False

    def test_returns_false_when_send_fails(self):
        task = _task("ask_hermes", {"question": "Pergunta?"}, contact_phone=OWNER)
        with (
            patch("app.agent.handlers._OWNER_PHONE", OWNER),
            patch("app.agent.handlers.send_message", return_value=False),
            patch("app.services.tasks.update_task", return_value=True),
        ):
            from app.agent.handlers import ask_hermes_handler
            assert ask_hermes_handler(task) is False


# ---------------------------------------------------------------------------
# compile_handler
# ---------------------------------------------------------------------------

class TestCompileHandler:
    def _compile_task(self, source_ids=None, instructions="Monte o roteiro"):
        return {
            "id": "compile-task-001",
            "type": "compile",
            "payload": {
                "instructions": instructions,
                "source_task_ids": source_ids or ["src-1", "src-2"],
            },
        }

    def _source_task(self, task_id, name, response=None):
        return {
            "id": task_id,
            "type": "collect_from_contact",
            "contact_phone": "5585999990001",
            "payload": {
                "contact_name": name,
                "response": response,
            },
        }

    def test_returns_true_and_saves_result(self):
        task = self._compile_task()
        sources = {
            "src-1": self._source_task("src-1", "João", "Eu farei a oração"),
            "src-2": self._source_task("src-2", "Maria", "Eu farei o louvor"),
        }
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Roteiro compilado"
        with (
            patch("app.services.tasks.get_task", side_effect=lambda tid: sources.get(tid)),
            patch("app.services.tasks.update_task", return_value=True) as mock_update,
            patch("app.agent.handlers.OpenAI") as mock_openai,
        ):
            mock_openai.return_value.chat.completions.create.return_value = mock_completion
            from app.agent.handlers import compile_handler
            result = compile_handler(task)
        assert result is True
        # Verifica que o resultado foi salvo no payload
        update_calls = mock_update.call_args_list
        payload_patches = [c.kwargs.get("payload_patch", {}) for c in update_calls]
        assert any("result" in p for p in payload_patches)

    def test_returns_false_when_no_instructions(self):
        task = self._compile_task(instructions="")
        from app.agent.handlers import compile_handler
        assert compile_handler(task) is False

    def test_returns_false_when_no_source_task_ids(self):
        task = self._compile_task(source_ids=[])
        from app.agent.handlers import compile_handler
        assert compile_handler(task) is False

    def test_returns_false_when_no_responses_collected(self):
        task = self._compile_task()
        sources = {
            "src-1": self._source_task("src-1", "João", response=None),
            "src-2": self._source_task("src-2", "Maria", response=None),
        }
        with patch("app.services.tasks.get_task", side_effect=lambda tid: sources.get(tid)):
            from app.agent.handlers import compile_handler
            result = compile_handler(task)
        assert result is False

    def test_compiles_with_partial_responses(self):
        task = self._compile_task()
        sources = {
            "src-1": self._source_task("src-1", "João", "Meu roteiro"),
            "src-2": self._source_task("src-2", "Pedro", response=None),  # sem resposta
        }
        mock_completion = MagicMock()
        mock_completion.choices[0].message.content = "Roteiro parcial"
        with (
            patch("app.services.tasks.get_task", side_effect=lambda tid: sources.get(tid)),
            patch("app.services.tasks.update_task", return_value=True),
            patch("app.agent.handlers.OpenAI") as mock_openai,
        ):
            mock_openai.return_value.chat.completions.create.return_value = mock_completion
            from app.agent.handlers import compile_handler
            result = compile_handler(task)
        assert result is True
        # Verifica que "Pedro" aparece na mensagem ao LLM como ausente
        call_args = mock_openai.return_value.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else [])
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        assert "Pedro" in user_msg

    def test_returns_false_on_llm_exception(self):
        task = self._compile_task()
        sources = {"src-1": self._source_task("src-1", "João", "resposta")}
        with (
            patch("app.services.tasks.get_task", side_effect=lambda tid: sources.get(tid)),
            patch("app.services.tasks.update_task", return_value=True),
            patch("app.agent.handlers.OpenAI") as mock_openai,
        ):
            mock_openai.return_value.chat.completions.create.side_effect = Exception("API error")
            from app.agent.handlers import compile_handler
            result = compile_handler(task)
        assert result is False

    def test_dispatches_compile(self):
        task = {"id": "c1", "type": "compile", "payload": {"instructions": "", "source_task_ids": []}}
        from app.agent.handlers import dispatch_handler
        # Sem instructions → False (mas já está no dispatch agora)
        result = dispatch_handler(task)
        assert result is False  # False por falta de instructions, não por tipo desconhecido


class TestSendMessageHandlerWithCompileSource:
    def test_uses_compile_result_when_content_empty(self):
        compile_task = {
            "id": "compile-1",
            "payload": {"result": "Roteiro compilado pelo LLM"},
        }
        task = {
            "id": "send-1",
            "type": "send_message",
            "payload": {
                "content": "",
                "target_type": "group",
                "targets": ["Jovens"],
                "source_compile_task_id": "compile-1",
            },
        }
        group = {"name": "Jovens", "jid": "111@g.us"}
        with (
            patch("app.agent.handlers.get_group_by_name", return_value=group),
            patch("app.agent.handlers.send_group_message", return_value=True) as mock_send,
            patch("app.services.tasks.get_task", return_value=compile_task),
        ):
            from app.agent.handlers import send_message_handler
            result = send_message_handler(task)
        mock_send.assert_called_once_with("111@g.us", "Roteiro compilado pelo LLM")
        assert result is True
