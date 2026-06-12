import logging
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    classify_intent,
    generate_draft,
    handle_unknown,
    manage_groups,
    query_history,
    recall_memory,
    save_memory,
    send_to_groups,
)

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    phone: str
    user_message: str
    intent: str
    draft: Optional[str]
    target_groups: list
    send_direct: bool
    response: str
    classification: dict
    memory_context: str  # context loaded from Obsidian vault by recall_memory


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _route_intent(state: AgentState) -> str:
    intent = state.get("intent", "unknown")
    return {
        "generate": "generate_draft",
        "send": "send_to_groups",
        "approve": "send_to_groups",
        "manage_groups": "manage_groups",
        "history": "query_history",
        "update_context": "save_memory",   # directly persist new info
        "add_task": "save_memory",         # directly add task to vault
    }.get(intent, "handle_unknown")


def _after_draft(state: AgentState) -> str:
    # send_direct: skip approval, go straight to send + save
    if state.get("send_direct") and state.get("draft"):
        return "send_to_groups"
    return END


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    g.add_node("recall_memory", recall_memory)
    g.add_node("classify_intent", classify_intent)
    g.add_node("generate_draft", generate_draft)
    g.add_node("send_to_groups", send_to_groups)
    g.add_node("manage_groups", manage_groups)
    g.add_node("save_memory", save_memory)
    g.add_node("query_history", query_history)
    g.add_node("handle_unknown", handle_unknown)

    # Recall context → classify → route
    g.add_edge(START, "recall_memory")
    g.add_edge("recall_memory", "classify_intent")
    g.add_conditional_edges("classify_intent", _route_intent)

    # Draft: show to user OR send directly
    g.add_conditional_edges("generate_draft", _after_draft)

    # Actions always persist to vault before finishing
    g.add_edge("send_to_groups", "save_memory")
    g.add_edge("manage_groups", "save_memory")
    g.add_edge("save_memory", END)

    # Read-only / no-action paths end directly
    g.add_edge("query_history", END)
    g.add_edge("handle_unknown", END)

    return g.compile()


_graph = _build_graph()

# In-memory session store: phone → {pending_draft, target_groups}
# Single-process deployment only (gunicorn --workers 1)
_sessions: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_agent(phone: str, message: str) -> str:
    session = _sessions.get(phone, {})

    initial: AgentState = {
        "phone": phone,
        "user_message": message,
        "intent": "",
        "draft": session.get("pending_draft"),
        "target_groups": session.get("target_groups", []),
        "send_direct": False,
        "response": "",
        "classification": {},
        "memory_context": "",
    }

    try:
        result = _graph.invoke(initial)
    except Exception as e:
        logger.error(f"Agent error for {phone}: {e}", exc_info=True)
        return "❌ Erro interno no agente. Tente novamente."

    intent = result.get("intent", "")
    send_direct = result.get("send_direct", False)
    has_draft = bool(result.get("draft"))

    if intent == "generate" and has_draft and not send_direct:
        _sessions[phone] = {
            "pending_draft": result["draft"],
            "target_groups": result.get("target_groups", []),
        }
    elif intent in ("send", "approve") or (intent == "generate" and send_direct):
        _sessions.pop(phone, None)

    return result.get("response", "")
