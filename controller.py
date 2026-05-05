from config.settings import DEFAULTS
from memory.manager import load_memory, update_memory
from state import TutorState, PipelineError
from modules import (
    context_select,
    context_resolve,
    interpret,
    policy,
    normalize,
    plan,
    solve,
    verify,
    coverage,
    assemble,
)


def build_config(user_config: dict | None = None) -> dict:
    config = DEFAULTS.copy()
    config.setdefault("enable_context_resolution", True)
    config.setdefault("context_turn_limit", 5)
    config.setdefault("summary_default_scope", "active_thread")

    if user_config:
        config.update(user_config)

    return config


def _safe_controller_failure(state: TutorState, e: Exception) -> TutorState:
    state.errors.append(
        PipelineError(
            module="controller",
            error_type="unexpected_error",
            message=f"Pipeline failed unexpectedly: {type(e).__name__}: {e}",
            recoverable=True,
        )
    )

    state.final_response = (
        "The tutoring system encountered an internal processing issue. Please "
        "rephrase the question as a direct math, history, or conversation-summary "
        "task."
    )

    return state


def _update_memory_safely(state: TutorState) -> TutorState:
    """
    Update memory after a completed pipeline run.

    Full controller-level crashes are not written to memory. Normal completed
    turns are written even if some recoverable module errors occurred. The
    memory manager decides whether the turn is summary-eligible.
    """
    try:
        state.memory = update_memory(state.memory, state)
    except Exception as e:
        state.errors.append(
            PipelineError(
                module="memory",
                error_type="unexpected_error",
                message=f"Memory update failed: {type(e).__name__}: {e}",
                recoverable=True,
            )
        )

    return state


def run_pipeline(
    raw_input: str,
    config: dict | None = None,
    memory: dict | None = None,
) -> TutorState:
    final_config = build_config(config)

    state = TutorState(
        raw_input=raw_input,
        config=final_config,
        memory=load_memory(memory),
    )

    try:
        if final_config.get("enable_context_resolution", True):
            state = context_select.run(state)
            state = context_resolve.run(state)
        else:
            state.resolved_input = state.raw_input

        state = interpret.run(state)
        state = policy.run(state)
        state = normalize.run(state)
        state = plan.run(state)
        state = solve.run(state)
        state = verify.run(state)
        state = coverage.run(state)

        if (
            state.coverage
            and not state.coverage.ok
            and final_config.get("max_retries", 0) > 0
            and state.tasks
        ):
            state = solve.run(state)
            state = verify.run(state)
            state = coverage.run(state)

        state = assemble.run(state)

        if not state.final_response:
            state.final_response = (
                "I could not produce a final response. Please rephrase the question "
                "as a direct math, history, or conversation-summary task."
            )

        state = _update_memory_safely(state)
        return state

    except Exception as e:
        state = _safe_controller_failure(state, e)
        return state