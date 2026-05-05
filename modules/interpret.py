from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import INTERPRET_SYSTEM_PROMPT, INTERPRET_USER_TEMPLATE
from llm.schemas import InterpretResponse
from state import Segment, TutorState, PipelineError


def _make_fallback_segment(
    raw_input: str,
    reason: str,
    note: str,
) -> Segment:
    return Segment(
        segment_id="seg_1",
        original_text=raw_input,
        structure_role="standalone_task",
        inferred_domain="unknown",
        constraints=[],
        notes=note,
        is_fallback=True,
        fallback_reason=reason,
    )


def _apply_interpret_fallback(
    state: TutorState,
    reason: str,
    note: str,
) -> TutorState:
    state.structure_type = "unknown"
    state.interpretation_note = note
    state.segments = [
        _make_fallback_segment(
            raw_input=state.raw_input,
            reason=reason,
            note=note,
        )
    ]

    state.errors.append(
        PipelineError(
            module="interpret",
            error_type=reason,
            message=note,
            recoverable=True,
        )
    )

    return state


def run(state: TutorState) -> TutorState:
    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    input_for_interpretation = state.resolved_input or state.raw_input

    context_resolution_json = "{}"
    if state.context_resolution:
        context_resolution_json = state.context_resolution.model_dump_json(indent=2)

    try:
        result = client.call_json(
            system_prompt=INTERPRET_SYSTEM_PROMPT,
            user_prompt=INTERPRET_USER_TEMPLATE.format(
                raw_input=state.raw_input,
                resolved_input=input_for_interpretation,
                context_resolution_json=context_resolution_json,
            ),
            response_model=InterpretResponse,
        )

    except LLMContentFilterError:
        return _apply_interpret_fallback(
            state=state,
            reason="provider_content_filter",
            note=(
                "The interpreter model call was blocked by the provider content filter "
                "before the request could be classified."
            ),
        )

    except LLMJSONParseError:
        return _apply_interpret_fallback(
            state=state,
            reason="interpreter_json_parse_error",
            note=(
                "The interpreter model returned output that could not be parsed into "
                "the expected schema."
            ),
        )

    except LLMProviderError:
        return _apply_interpret_fallback(
            state=state,
            reason="llm_provider_error",
            note="The interpreter model call failed due to a provider/API error.",
        )

    except Exception as e:
        return _apply_interpret_fallback(
            state=state,
            reason="unexpected_error",
            note=f"The interpreter failed unexpectedly: {type(e).__name__}: {e}",
        )

    state.structure_type = result.structure_type
    state.interpretation_note = result.interpretation_note
    state.segments = [Segment.model_validate(s.model_dump()) for s in result.segments]
    return state