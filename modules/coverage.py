from state import CoverageResult, TutorState


def run(state: TutorState) -> TutorState:
    fallback_segment_ids = {
        s.segment_id for s in state.segments if getattr(s, "is_fallback", False)
    }

    handled = {
        d.segment_id
        for d in state.decisions
        if d.decision in {"accept", "transform", "abstract"}
        and d.can_be_handled_as_tutoring_task
        and d.segment_id not in fallback_segment_ids
    }

    answered = {a.segment_id for a in state.answers}

    missing = sorted(list(handled - answered))
    unexpected = sorted(list(answered - handled))

    notes = []

    if fallback_segment_ids:
        notes.append(
            "Some segments were fallback segments created after an upstream interpretation failure."
        )

    if missing:
        notes.append("Some handled segments did not receive answers.")

    if unexpected:
        notes.append("Some answered segments were not marked as handled by policy.")

    failed_verifications = [
        r for r in state.verification_records
        if not r.ok
    ]

    if failed_verifications:
        notes.append("Some verification checks failed.")

    state.coverage = CoverageResult(
        ok=(len(missing) == 0 and len(unexpected) == 0 and len(failed_verifications) == 0),
        missing_segment_ids=missing,
        unexpected_answer_segment_ids=unexpected,
        notes=notes,
    )

    return state