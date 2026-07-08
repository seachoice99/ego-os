from ego_os import model_provider, store

# Which capability a specialist uses to actually produce work. Orchestrator
# only ever sees required_capabilities from the registry; this mapping is
# what turns "the chosen specialist" into "the capability tag to call".
EXECUTION_CAPABILITY = {
    "writer": "business_communication",
    "researcher": "synthesis",
}


def _select_specialist(request_text):
    """Orchestrator genuinely chooses between more than one specialist by
    required capability, instead of a fixed rule."""
    roster = store.get_roster_summary(list(EXECUTION_CAPABILITY.keys()))
    roster_description = "\n".join(
        f"- {r['id']}: {r['title']}. Mission: {r['mission']}. Capabilities: {', '.join(r['required_capabilities'])}."
        for r in roster
    )
    prompt = (
        "You are the Orchestrator at a digital company, deciding who should staff a task.\n\n"
        f"Available specialists:\n{roster_description}\n\n"
        f"Owner's request:\n{request_text}\n\n"
        "Reply with exactly one word: the id of the single best-suited specialist, nothing else."
    )
    decision_text, in_tok, out_tok, cost = model_provider.complete("delegation", prompt)
    decision = decision_text.strip().lower()
    for candidate_id in EXECUTION_CAPABILITY:
        if candidate_id in decision:
            return candidate_id, in_tok, out_tok, cost
    return "writer", in_tok, out_tok, cost  # safe default if the reply was ambiguous


def _run_specialist(specialist_id, title, mission, request_text, memory_context, feedback=None):
    capability = EXECUTION_CAPABILITY[specialist_id]
    context_block = ""
    if memory_context:
        context_block = "Prior context from this company's memory:\n" + "\n".join(f"- {m}" for m in memory_context) + "\n\n"
    revision_block = f"\n\nA QA reviewer asked for a revision: {feedback}\nProduce a corrected version." if feedback else ""
    prompt = (
        f"You are the {title} at a digital company. Mission: {mission}\n\n"
        f"{context_block}"
        f"Fulfil this request from the Owner as a clear, complete artifact:\n\n{request_text}"
        f"{revision_block}"
    )
    return model_provider.complete(capability, prompt)


def _run_qa(request_text, draft_text):
    qa_prompt = (
        "You are the QA Reviewer at a digital company. Original request:\n"
        f"{request_text}\n\nDraft:\n{draft_text}\n\n"
        "Reply with PASS if the draft satisfies the request, or REVISE: <reason> if not."
    )
    return model_provider.complete("critique", qa_prompt)


def run(task_id: int, project_id: int, request_text: str):
    """Run the documented Task Lifecycle for one task:
    Intake -> Planning -> Staffing -> Execution -> QA -> Delivery -> Memory Update.

    QA is a real gate: a REVISE verdict sends the draft back for exactly
    one corrected attempt before delivery, rather than being recorded and
    ignored."""
    timeline = []
    total_in = total_out = 0
    total_cost = 0.0

    # Intake
    timeline.append({"step": "intake", "employee": "orchestrator", "detail": "Received request from Owner."})

    # Planning
    store.update_task_status(task_id, "planning")
    store.set_employee_status("orchestrator", "assigned")
    memory_context = store.get_recent_memory(project_id)
    timeline.append({"step": "planning", "employee": "orchestrator", "detail": "Reviewed request and prior project memory."})

    # Staffing
    store.update_task_status(task_id, "staffing")
    specialist_id, s_in, s_out, s_cost = _select_specialist(request_text)
    total_in += s_in
    total_out += s_out
    total_cost += s_cost
    roster = store.get_roster_summary([specialist_id])[0]
    timeline.append({"step": "staffing", "employee": "orchestrator", "detail": f"Assigned {roster['title']} and QA Reviewer."})

    # Execution
    store.update_task_status(task_id, "execution")
    store.set_employee_status(specialist_id, "assigned")
    draft_text, w_in, w_out, w_cost = _run_specialist(
        specialist_id, roster["title"], roster["mission"], request_text, memory_context
    )
    total_in += w_in
    total_out += w_out
    total_cost += w_cost
    timeline.append({"step": "execution", "employee": specialist_id, "detail": f"Drafted a response as {roster['title']}."})

    # QA
    store.update_task_status(task_id, "qa")
    store.set_employee_status("qa", "assigned")
    qa_note, q_in, q_out, q_cost = _run_qa(request_text, draft_text)
    total_in += q_in
    total_out += q_out
    total_cost += q_cost
    timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})

    if qa_note.strip().upper().startswith("REVISE"):
        draft_text, r_in, r_out, r_cost = _run_specialist(
            specialist_id, roster["title"], roster["mission"], request_text, memory_context, feedback=qa_note
        )
        total_in += r_in
        total_out += r_out
        total_cost += r_cost
        timeline.append({"step": "revision", "employee": specialist_id, "detail": "Produced a corrected draft based on QA feedback."})

        qa_note, q2_in, q2_out, q2_cost = _run_qa(request_text, draft_text)
        total_in += q2_in
        total_out += q2_out
        total_cost += q2_cost
        timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})

    store.set_employee_status(specialist_id, "idle")
    store.set_employee_status("qa", "idle")

    # Delivery
    store.update_task_status(task_id, "delivered")
    store.set_employee_status("orchestrator", "idle")
    timeline.append({"step": "delivery", "employee": "orchestrator", "detail": "Delivered result and report to Owner."})

    store.create_report(
        task_id=task_id,
        employees_involved=["orchestrator", specialist_id, "qa"],
        timeline=timeline,
        input_tokens=total_in,
        output_tokens=total_out,
        cost=total_cost,
        result_text=draft_text,
        qa_note=qa_note,
    )

    # Memory Update
    store.create_memory_entry(
        task_id, summary=f"Task #{task_id} ({roster['title']}): {request_text[:120]!r} -> delivered."
    )
