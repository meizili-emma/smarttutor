import json

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import NORMALIZE_SYSTEM_PROMPT, NORMALIZE_USER_TEMPLATE
from llm.schemas import NormalizeResponse
from state import TutorState, PipelineError


def _record_normalize_error(state: TutorState, error_type: str, message: str) -> TutorState:
    state.errors.append(
        PipelineError(
            module="normalize",
            error_type=error_type,
            message=message,
            recoverable=True,
        )
    )

    # Conservative fallback:
    # - accept/transform: use original segment text as transformed_task_text
    # - abstract: use original segment text as abstracted_task_text
    segment_map = {s.segment_id: s for s in state.segments}

    for decision in state.decisions:
        if decision.decision not in {"accept", "transform", "abstract"}:
            continue

        seg = segment_map.get(decision.segment_id)
        if not seg:
            continue

        if decision.decision in {"accept", "transform"} and not decision.transformed_task_text:
            decision.transformed_task_text = seg.original_text

        if decision.decision == "abstract" and not decision.abstracted_task_text:
            decision.abstracted_task_text = seg.original_text

    return state


def run(state: TutorState) -> TutorState:
    handled_segments = []

    for seg in state.segments:
        if getattr(seg, "is_fallback", False):
            continue

        decision = next((d for d in state.decisions if d.segment_id == seg.segment_id), None)
        if not decision:
            continue

        if decision.decision in {"accept", "transform", "abstract"}:
            handled_segments.append({
                "segment_id": seg.segment_id,
                "original_text": seg.original_text,
                "decision": decision.decision,
                "handled_domain": decision.handled_domain,
                "transformed_task_text": decision.transformed_task_text,
                "abstracted_task_text": decision.abstracted_task_text,
            })

    if not handled_segments:
        return state

    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    context_resolution_json = (
        state.context_resolution.model_dump_json(indent=2)
        if state.context_resolution
        else "{}"
    )

    try:
        result = client.call_json(
            system_prompt=NORMALIZE_SYSTEM_PROMPT,
            user_prompt=NORMALIZE_USER_TEMPLATE.format(
                raw_input=state.raw_input,
                resolved_input=state.resolved_input or state.raw_input,
                context_resolution_json=context_resolution_json,
                handled_segments_json=json.dumps(
                    handled_segments,
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
            response_model=NormalizeResponse,
        )

    except LLMContentFilterError:
        return _record_normalize_error(
            state,
            error_type="provider_content_filter",
            message="The normalize model call was blocked by the provider content filter.",
        )

    except LLMJSONParseError:
        return _record_normalize_error(
            state,
            error_type="normalize_json_parse_error",
            message="The normalize model returned output that could not be parsed into the expected schema.",
        )

    except LLMProviderError:
        return _record_normalize_error(
            state,
            error_type="llm_provider_error",
            message="The normalize model call failed due to a provider/API error.",
        )

    except Exception as e:
        return _record_normalize_error(
            state,
            error_type="unexpected_error",
            message=f"The normalize module failed unexpectedly: {type(e).__name__}: {e}",
        )

    normalized_map = {
        item.segment_id: item.normalized_text
        for item in result.normalized_segments
    }

    for decision in state.decisions:
        normalized_text = normalized_map.get(decision.segment_id)
        if not normalized_text:
            continue

        if decision.decision in {"accept", "transform"}:
            decision.transformed_task_text = normalized_text
        elif decision.decision == "abstract":
            decision.abstracted_task_text = normalized_text

    return state