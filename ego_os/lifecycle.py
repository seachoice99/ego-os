from ego_os import model_provider, store


def run(task_id: int, request_text: str):
    """Run the documented Task Lifecycle for one task:
    Intake -> Planning -> Staffing -> Execution -> QA -> Delivery -> Memory Update.

    Staffing is a fixed rule for Phase 0 (Writer drafts, QA reviews) --
    there is only one candidate specialist, so there is nothing for
    Orchestrator to actually decide yet."""
    timeline = []

    # Intake (task row already created with status 'intake' by the caller)
    timeline.append({"step": "intake", "employee": "orchestrator", "detail": "Received request from Owner."})

    # Planning
    store.update_task_status(task_id, "planning")
    store.set_employee_status("orchestrator", "assigned")
    timeline.append({"step": "planning", "employee": "orchestrator", "detail": "Routed to Writer for drafting, QA for review."})

    # Staffing
    store.update_task_status(task_id, "staffing")
    timeline.append({"step": "staffing", "employee": "orchestrator", "detail": "Assigned Writer and QA Reviewer."})

    # Execution
    store.update_task_status(task_id, "execution")
    store.set_employee_status("writer", "assigned")
    writer_prompt = (
        "You are the Writer at a digital company. Fulfil this request from the Owner "
        f"as a clear, complete written artifact:\n\n{request_text}"
    )
    draft_text, w_in, w_out, w_cost = model_provider.complete("business_communication", writer_prompt)
    store.set_employee_status("writer", "idle")
    timeline.append({"step": "execution", "employee": "writer", "detail": "Drafted a response."})

    # QA
    store.update_task_status(task_id, "qa")
    store.set_employee_status("qa", "assigned")
    qa_prompt = (
        "You are the QA Reviewer at a digital company. Original request:\n"
        f"{request_text}\n\nDraft:\n{draft_text}\n\n"
        "Reply with PASS if the draft satisfies the request, or REVISE: <reason> if not."
    )
    qa_note, q_in, q_out, q_cost = model_provider.complete("critique", qa_prompt)
    store.set_employee_status("qa", "idle")
    timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})

    # Delivery
    store.update_task_status(task_id, "delivered")
    store.set_employee_status("orchestrator", "idle")
    timeline.append({"step": "delivery", "employee": "orchestrator", "detail": "Delivered result and report to Owner."})

    store.create_report(
        task_id=task_id,
        employees_involved=["orchestrator", "writer", "qa"],
        timeline=timeline,
        input_tokens=w_in + q_in,
        output_tokens=w_out + q_out,
        cost=w_cost + q_cost,
        result_text=draft_text,
        qa_note=qa_note,
    )

    # Memory Update
    store.create_memory_entry(task_id, summary=f"Task #{task_id}: {request_text[:120]!r} -> delivered.")
