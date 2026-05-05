from state import Task, TutorState, PipelineError


SUPPORTED_DOMAINS = {"math", "history", "summary"}


def _segment_by_id(state: TutorState) -> dict:
    return {
        segment.segment_id: segment
        for segment in state.segments
    }


def _decision_by_segment_id(state: TutorState) -> dict:
    return {
        decision.segment_id: decision
        for decision in state.decisions
    }


def _is_branch_segment(seg) -> bool:
    return getattr(seg, "structure_role", None) == "branch"


def _branch_can_be_planned(seg, decision) -> bool:
    """
    Branch segments are condition-dependent.

    To avoid treating a conditional branch as a standalone task,
    only allow a branch to become a task when policy has explicitly
    transformed or abstracted it into a clean tutoring task.
    """
    if not _is_branch_segment(seg):
        return True

    return decision.decision in {"transform", "abstract"}


def _task_text_from_decision(seg, decision) -> str | None:
    if decision.decision in {"accept", "transform"}:
        return decision.transformed_task_text or seg.original_text

    if decision.decision == "abstract":
        return decision.abstracted_task_text or seg.original_text

    return None


def run(state: TutorState) -> TutorState:
    tasks = []
    counter = 1

    decision_map = _decision_by_segment_id(state)

    relation = "standalone"
    referenced_turn_ids = []
    summary_scope = None
    summary_domain_filter = None
    context_used = False

    if state.context_resolution:
        relation = state.context_resolution.relation_to_previous
        referenced_turn_ids = state.context_resolution.referenced_turn_ids
        summary_scope = state.context_resolution.summary_scope
        summary_domain_filter = state.context_resolution.summary_domain_filter
        context_used = state.context_resolution.needs_previous_context

    for seg in state.segments:
        if getattr(seg, "is_fallback", False):
            continue

        decision = decision_map.get(seg.segment_id)
        if decision is None:
            continue

        if decision.decision not in {"accept", "transform", "abstract"}:
            continue

        if not decision.can_be_handled_as_tutoring_task:
            continue

        if not _branch_can_be_planned(seg, decision):
            state.errors.append(
                PipelineError(
                    module="plan",
                    error_type="schema_validation_error",
                    message=(
                        f"Segment {seg.segment_id} is a conditional branch and was "
                        "accepted without transformation. Branch segments must be "
                        "transformed or abstracted before becoming standalone tasks."
                    ),
                    recoverable=True,
                )
            )
            continue

        if (
            decision.decision in {"accept", "transform"}
            and decision.can_be_handled_as_tutoring_task
            and decision.handled_domain is None
            and seg.inferred_domain == "summary"
        ):
            decision.handled_domain = "summary"

        if decision.handled_domain not in SUPPORTED_DOMAINS:
            state.errors.append(
                PipelineError(
                    module="plan",
                    error_type="schema_validation_error",
                    message=(
                        f"Segment {seg.segment_id} was marked handled, but "
                        f"handled_domain was invalid: {decision.handled_domain}"
                    ),
                    recoverable=True,
                )
            )
            continue

        task_text = _task_text_from_decision(seg, decision)

        if not task_text or not task_text.strip():
            state.errors.append(
                PipelineError(
                    module="plan",
                    error_type="schema_validation_error",
                    message=f"Segment {seg.segment_id} had no usable task text.",
                    recoverable=True,
                )
            )
            continue

        solver_name = {
            "math": "math_solver",
            "history": "history_solver",
            "summary": "summary_solver",
        }[decision.handled_domain]

        tasks.append(
            Task(
                task_id=f"t{counter}",
                segment_id=seg.segment_id,
                task_type=decision.handled_domain,
                task_text=task_text,
                solver_name=solver_name,
                style=state.config.get("style", "step_by_step"),
                constraints=getattr(seg, "constraints", []),
                context_used=context_used,
                source_relation=relation,
                referenced_turn_ids=referenced_turn_ids,
                summary_scope=summary_scope if decision.handled_domain == "summary" else None,
                summary_domain_filter=summary_domain_filter if decision.handled_domain == "summary" else None,
            )
        )
        counter += 1

    state.tasks = tasks
    return state