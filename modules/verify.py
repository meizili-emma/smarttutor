from state import VerificationRecord, TutorState


def _verify_context_resolution_exists(state: TutorState) -> list[VerificationRecord]:
    records = []

    if not state.context_resolution:
        return records

    if state.context_resolution.needs_previous_context and not state.context_resolution.resolved_input:
        records.append(
            VerificationRecord(
                check_type="context_resolution_exists",
                ok=False,
                issue="The turn needed previous context, but no resolved input was produced.",
            )
        )

    return records


def _verify_referenced_turns_exist(state: TutorState) -> list[VerificationRecord]:
    records = []

    if not state.context_resolution:
        return records

    referenced = set(state.context_resolution.referenced_turn_ids or [])
    if not referenced:
        return records

    memory_turns = state.memory.get("recent_turns", []) if isinstance(state.memory, dict) else []
    existing = {
        turn.get("turn_id")
        for turn in memory_turns
        if isinstance(turn, dict)
    }

    missing = sorted(list(referenced - existing))
    if missing:
        records.append(
            VerificationRecord(
                check_type="referenced_turns_exist",
                ok=False,
                issue=f"Referenced turn IDs were not found in memory: {missing}",
            )
        )

    return records


def _verify_summary_context_non_empty(state: TutorState) -> list[VerificationRecord]:
    records = []

    if not state.context_resolution:
        return records

    if state.context_resolution.relation_to_previous != "summary_request":
        return records

    has_answer = any(
        answer.task_type == "summary"
        and answer.answer_text
        and answer.solver_notes != "summary_no_successful_tutoring_content"
        for answer in state.answers
    )

    if not has_answer:
        records.append(
            VerificationRecord(
                check_type="summary_context_non_empty",
                ok=False,
                issue="The user asked for a summary, but no usable summary context was found.",
            )
        )

    return records


def run(state: TutorState) -> TutorState:
    records = []

    task_ids_with_answers = {a.task_id for a in state.answers}
    answer_by_task_id = {a.task_id: a for a in state.answers}

    for task in state.tasks:
        if task.task_id not in task_ids_with_answers:
            records.append(
                VerificationRecord(
                    check_type="answer_exists",
                    ok=False,
                    segment_id=task.segment_id,
                    task_id=task.task_id,
                    issue="No answer was generated for this task.",
                )
            )
            continue

        answer = answer_by_task_id[task.task_id]
        if not answer.answer_text or not answer.answer_text.strip():
            records.append(
                VerificationRecord(
                    check_type="answer_non_empty",
                    ok=False,
                    segment_id=task.segment_id,
                    task_id=task.task_id,
                    issue="Generated answer is empty.",
                )
            )
            continue

        records.append(
            VerificationRecord(
                check_type="answer_non_empty",
                ok=True,
                segment_id=task.segment_id,
                task_id=task.task_id,
                issue=None,
            )
        )

    records.extend(_verify_context_resolution_exists(state))
    records.extend(_verify_referenced_turns_exist(state))
    records.extend(_verify_summary_context_non_empty(state))

    state.verification_records = records
    return state