import json

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import (
    MATH_SOLVER_SYSTEM_PROMPT,
    MATH_SOLVER_USER_TEMPLATE,
    HISTORY_SOLVER_SYSTEM_PROMPT,
    HISTORY_SOLVER_USER_TEMPLATE,
    SUMMARY_SOLVER_SYSTEM_PROMPT,
    SUMMARY_SOLVER_USER_TEMPLATE,
)
from llm.schemas import SolveResponse
from state import AnswerRecord, TutorState, PipelineError


def _safe_solver_failure_answer(task, error_type: str) -> AnswerRecord:
    if task.task_type == "summary":
        answer_text = (
            "I could not generate a reliable summary from the available memory. "
            "Please try again after asking one or more math or history questions in separate turns."
        )
    else:
        answer_text = (
            "I could not generate a reliable tutoring answer for this part because "
            "the solver call failed. Please rephrase the question more directly."
        )

    return AnswerRecord(
        task_id=task.task_id,
        segment_id=task.segment_id,
        task_type=task.task_type,
        answer_text=answer_text,
        solver_notes=f"solver_failed:{error_type}",
    )


def _record_solver_error(
    state: TutorState,
    task,
    error_type: str,
    message: str,
) -> None:
    state.errors.append(
        PipelineError(
            module="solve",
            error_type=error_type,
            message=f"Task {task.task_id} / segment {task.segment_id}: {message}",
            recoverable=True,
        )
    )


def _call_math_solver(client: LLMClient, task) -> SolveResponse:
    return client.call_json(
        system_prompt=MATH_SOLVER_SYSTEM_PROMPT,
        user_prompt=MATH_SOLVER_USER_TEMPLATE.format(
            task_text=task.task_text,
            style=task.style,
        ),
        response_model=SolveResponse,
    )


def _call_history_solver(client: LLMClient, task) -> SolveResponse:
    constraints_text = (
        "; ".join(task.constraints)
        if getattr(task, "constraints", None)
        else "None"
    )

    return client.call_json(
        system_prompt=HISTORY_SOLVER_SYSTEM_PROMPT,
        user_prompt=HISTORY_SOLVER_USER_TEMPLATE.format(
            task_text=task.task_text,
            constraints=constraints_text,
            style=task.style,
        ),
        response_model=SolveResponse,
    )


def _shorten_for_summary(text: str | None, max_chars: int = 500) -> str:
    text = " ".join((text or "").strip().split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _is_usable_recent_turn(turn: dict) -> bool:
    if not isinstance(turn, dict):
        return False

    if turn.get("summary_eligible") is False:
        return False

    if turn.get("summary_only") is True:
        return False

    if turn.get("status") not in {"answered", "other"}:
        return False

    user_text = (turn.get("user") or "").strip()
    assistant_text = (turn.get("assistant") or "").strip()

    return bool(user_text and assistant_text)


def _build_summary_memory_context(memory: dict | None) -> dict:
    """
    Build selected memory for true LLM summarization.

    Code decides whether usable memory exists.
    The LLM only writes the natural-language summary.
    """
    if not isinstance(memory, dict):
        return {
            "has_usable_memory": False,
            "empty_reason": "memory_missing_or_malformed",
            "taught_topics": [],
            "recent_turns": [],
            "session_brief": "",
        }

    learning_records = [
    {
        "domain": item.get("domain"),
        "topic_title": item.get("topic_title"),
        "learning_summary": item.get("learning_summary"),
        "key_concepts": item.get("key_concepts", []),
    }
    for item in memory.get("learning_records", [])
    if isinstance(item, dict)
    and item.get("domain")
    and (item.get("topic_title") or item.get("learning_summary"))
]

    recent_turns = []

    for turn in memory.get("recent_turns", []):
        if not _is_usable_recent_turn(turn):
            continue

        recent_turns.append(
            {
                "user": _shorten_for_summary(
                    turn.get("user", ""),
                    max_chars=500,
                ),
                "assistant": _shorten_for_summary(
                    turn.get("assistant", ""),
                    max_chars=800,
                ),
                "task_domains": turn.get("task_domains", []),
                "status": turn.get("status", ""),
            }
        )

    session_summary = memory.get("session_summary", {})
    session_brief = ""
    if isinstance(session_summary, dict):
        session_brief = (session_summary.get("brief") or "").strip()

    has_usable_memory = bool(learning_records or recent_turns or session_brief)

    return {
        "has_usable_memory": has_usable_memory,
        "empty_reason": "" if has_usable_memory else "no_successful_tutoring_content",
        "learning_records": learning_records[-12:],
        "recent_turns": recent_turns[-12:],
        "session_brief": session_brief,
    }


def _empty_summary_response(summary_context: dict) -> SolveResponse:
    reason = summary_context.get("empty_reason", "")

    if reason == "memory_missing_or_malformed":
        return SolveResponse(
            answer_text=(
                "I do not have enough previous conversation in this session to "
                "summarize yet."
            ),
            solver_notes="summary_memory_missing_or_malformed",
        )

    if "active_thread" in reason:
        return SolveResponse(
            answer_text=(
                "I do not have enough content in the current tutoring thread to "
                "summarize yet."
            ),
            solver_notes="summary_no_successful_tutoring_content",
        )

    if "latest_turn" in reason:
        return SolveResponse(
            answer_text=(
                "I do not have a previous completed turn available to summarize yet."
            ),
            solver_notes="summary_no_successful_tutoring_content",
        )

    return SolveResponse(
        answer_text=(
            "I do not have enough successful tutoring content in this session to "
            "summarize yet."
        ),
        solver_notes="summary_no_successful_tutoring_content",
    )


def _turn_is_usable_for_summary(turn: dict) -> bool:
    if not isinstance(turn, dict):
        return False

    if turn.get("summary_only") is True:
        return False

    if turn.get("summary_eligible") is False:
        return False

    user_text = (turn.get("user") or "").strip()
    assistant_text = (turn.get("assistant") or "").strip()

    return bool(user_text and assistant_text)


def _compact_turn(turn: dict) -> dict:
    return {
        "turn_id": turn.get("turn_id", ""),
        "thread_id": turn.get("thread_id", ""),
        "user": _shorten_for_summary(turn.get("user", ""), max_chars=600),
        "assistant": _shorten_for_summary(turn.get("assistant", ""), max_chars=900),
        "task_domains": turn.get("task_domains", []),
        "status": turn.get("status", ""),
        "relation_to_previous": turn.get("relation_to_previous", "standalone"),
        "resolved_input": _shorten_for_summary(turn.get("resolved_input", ""), max_chars=600),
    }


def _build_latest_turn_summary_context(memory: dict) -> dict:
    turns = [
        turn for turn in memory.get("recent_turns", [])
        if _turn_is_usable_for_summary(turn)
    ]

    if not turns:
        return {
            "has_usable_memory": False,
            "empty_reason": "no_usable_latest_turn",
            "scope": "latest_turn",
        }

    return {
        "has_usable_memory": True,
        "scope": "latest_turn",
        "recent_turns": [_compact_turn(turns[-1])],
        "active_thread": {},
        "learning_records": [],
        "session_summary": memory.get("session_summary", {}),
    }


def _build_active_thread_summary_context(memory: dict) -> dict:
    active_thread = memory.get("active_thread", {})
    if not isinstance(active_thread, dict):
        active_thread = {}

    thread_id = active_thread.get("thread_id", "")
    thread_turn_ids = set(active_thread.get("turn_ids", []) or [])

    recent_turns = []
    for turn in memory.get("recent_turns", []):
        if not _turn_is_usable_for_summary(turn):
            continue

        if thread_turn_ids and turn.get("turn_id") in thread_turn_ids:
            recent_turns.append(_compact_turn(turn))
        elif thread_id and turn.get("thread_id") == thread_id:
            recent_turns.append(_compact_turn(turn))

    has_thread_content = bool(active_thread.get("topic_title") or recent_turns)

    if not has_thread_content:
        return {
            "has_usable_memory": False,
            "empty_reason": "no_active_thread_content",
            "scope": "active_thread",
        }

    return {
        "has_usable_memory": True,
        "scope": "active_thread",
        "active_thread": active_thread,
        "recent_turns": recent_turns[-8:],
        "learning_records": [],
        "session_summary": memory.get("session_summary", {}),
    }


def _build_recent_session_summary_context(memory: dict) -> dict:
    turns = [
        _compact_turn(turn)
        for turn in memory.get("recent_turns", [])
        if _turn_is_usable_for_summary(turn)
    ]

    if not turns:
        return {
            "has_usable_memory": False,
            "empty_reason": "no_usable_recent_session",
            "scope": "recent_session",
        }

    return {
        "has_usable_memory": True,
        "scope": "recent_session",
        "recent_turns": turns[-10:],
        "active_thread": memory.get("active_thread", {}),
        "learning_records": [],
        "session_summary": memory.get("session_summary", {}),
    }


def _build_whole_session_summary_context(memory: dict) -> dict:
    records = [
        {
            "domain": item.get("domain"),
            "topic_title": item.get("topic_title"),
            "learning_summary": item.get("learning_summary"),
            "key_concepts": item.get("key_concepts", []),
        }
        for item in memory.get("learning_records", [])
        if isinstance(item, dict)
        and item.get("domain")
        and (item.get("topic_title") or item.get("learning_summary"))
    ]

    turns = [
        _compact_turn(turn)
        for turn in memory.get("recent_turns", [])
        if _turn_is_usable_for_summary(turn)
    ]

    session_summary = memory.get("session_summary", {})
    has_summary = isinstance(session_summary, dict) and bool(session_summary.get("brief"))

    if not records and not turns and not has_summary:
        return {
            "has_usable_memory": False,
            "empty_reason": "no_usable_whole_session",
            "scope": "whole_session",
        }

    return {
        "has_usable_memory": True,
        "scope": "whole_session",
        "session_summary": session_summary,
        "learning_records": records[-15:],
        "recent_turns": turns[-12:],
        "active_thread": memory.get("active_thread", {}),
    }


def _build_domain_filtered_summary_context(memory: dict, domain: str | None) -> dict:
    if domain not in {"math", "history", "summary"}:
        return _build_whole_session_summary_context(memory)

    records = [
        {
            "domain": item.get("domain"),
            "topic_title": item.get("topic_title"),
            "learning_summary": item.get("learning_summary"),
            "key_concepts": item.get("key_concepts", []),
        }
        for item in memory.get("learning_records", [])
        if isinstance(item, dict) and item.get("domain") == domain
    ]

    turns = []
    for turn in memory.get("recent_turns", []):
        if not _turn_is_usable_for_summary(turn):
            continue
        if domain in (turn.get("task_domains", []) or []):
            turns.append(_compact_turn(turn))

    if not records and not turns:
        return {
            "has_usable_memory": False,
            "empty_reason": f"no_usable_{domain}_content",
            "scope": "domain_filtered",
            "domain_filter": domain,
        }

    return {
        "has_usable_memory": True,
        "scope": "domain_filtered",
        "domain_filter": domain,
        "learning_records": records[-12:],
        "recent_turns": turns[-10:],
        "active_thread": memory.get("active_thread", {}),
        "session_summary": memory.get("session_summary", {}),
    }


def _build_summary_memory_context(
    memory: dict | None,
    context_resolution=None,
    task=None,
) -> dict:
    if not isinstance(memory, dict):
        return {
            "has_usable_memory": False,
            "empty_reason": "memory_missing_or_malformed",
            "scope": "unknown",
        }

    scope = None
    domain_filter = None

    if task is not None:
        scope = getattr(task, "summary_scope", None)
        domain_filter = getattr(task, "summary_domain_filter", None)

    if context_resolution is not None:
        scope = scope or getattr(context_resolution, "summary_scope", None)
        domain_filter = domain_filter or getattr(context_resolution, "summary_domain_filter", None)

    scope = scope or "active_thread"

    if scope == "latest_turn":
        return _build_latest_turn_summary_context(memory)

    if scope == "active_thread":
        return _build_active_thread_summary_context(memory)

    if scope == "recent_session":
        return _build_recent_session_summary_context(memory)

    if scope == "whole_session":
        return _build_whole_session_summary_context(memory)

    if scope == "domain_filtered":
        return _build_domain_filtered_summary_context(memory, domain_filter)

    return _build_active_thread_summary_context(memory)



def _call_summary_solver(
    client: LLMClient,
    state: TutorState,
    task,
) -> SolveResponse:
    summary_context = _build_summary_memory_context(
        state.memory,
        context_resolution=state.context_resolution,
        task=task,
    )

    if not summary_context["has_usable_memory"]:
        return _empty_summary_response(summary_context)

    return client.call_json(
        system_prompt=SUMMARY_SOLVER_SYSTEM_PROMPT,
        user_prompt=SUMMARY_SOLVER_USER_TEMPLATE.format(
            task_text=task.task_text,
            style=task.style,
            summary_scope=summary_context.get("scope", "unknown"),
            memory_json=json.dumps(summary_context, ensure_ascii=False, indent=2),
        ),
        response_model=SolveResponse,
    )


def _call_solver(
    client: LLMClient,
    state: TutorState,
    task,
) -> SolveResponse:
    if task.solver_name == "math_solver":
        return _call_math_solver(client, task)

    if task.solver_name == "history_solver":
        return _call_history_solver(client, task)

    if task.solver_name == "summary_solver":
        return _call_summary_solver(client, state, task)

    raise ValueError(f"Unknown solver: {task.solver_name}")


def run(state: TutorState) -> TutorState:
    if not state.tasks:
        state.answers = []
        return state

    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    answers = []

    for task in state.tasks:
        try:
            result = _call_solver(client, state, task)

            answer_text = result.answer_text
            if not isinstance(answer_text, str):
                answer_text = json.dumps(answer_text, ensure_ascii=False)

            solver_notes = result.solver_notes
            if not isinstance(solver_notes, str) or not solver_notes.strip():
                solver_notes = "ok"

            answers.append(
                AnswerRecord(
                    task_id=task.task_id,
                    segment_id=task.segment_id,
                    task_type=task.task_type,
                    answer_text=answer_text,
                    solver_notes=solver_notes.strip(),
                )
            )

        except LLMContentFilterError:
            _record_solver_error(
                state,
                task,
                error_type="provider_content_filter",
                message="The solver model call was blocked by the provider content filter.",
            )
            answers.append(_safe_solver_failure_answer(task, "provider_content_filter"))

        except LLMJSONParseError:
            _record_solver_error(
                state,
                task,
                error_type="solver_json_parse_error",
                message=(
                    "The solver model returned output that could not be parsed into "
                    "the expected schema."
                ),
            )
            answers.append(_safe_solver_failure_answer(task, "solver_json_parse_error"))

        except LLMProviderError:
            _record_solver_error(
                state,
                task,
                error_type="llm_provider_error",
                message="The solver model call failed due to a provider/API error.",
            )
            answers.append(_safe_solver_failure_answer(task, "llm_provider_error"))

        except Exception as e:
            _record_solver_error(
                state,
                task,
                error_type="unexpected_error",
                message=f"The solver failed unexpectedly: {type(e).__name__}: {e}",
            )
            answers.append(_safe_solver_failure_answer(task, "unexpected_error"))

    state.answers = answers
    return state