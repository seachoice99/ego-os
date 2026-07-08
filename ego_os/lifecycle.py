import json
from datetime import date

from ego_os import model_provider, store, tools


def _today_line():
    """Models don't otherwise know today's real date, and will misjudge
    which live search/tool results are current vs. future -- found during
    Web Research verification (v0.2)."""
    return f"Today's date is {date.today().isoformat()}.\n\n"

# Which capability a specialist uses to actually produce work. Orchestrator
# only ever sees required_capabilities from the registry; this mapping is
# what turns "the chosen specialist" into "the capability tag to call".
EXECUTION_CAPABILITY = {
    "writer": "business_communication",
    "researcher": "synthesis",
    "coder": "coding",
    "cfo": "cost_accounting",
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


def _tool_prompt_block(permissions):
    available = tools.available_tools(permissions)
    if not available:
        return ""
    tool_lines = "\n".join(f"- {t['description']}" for t in available)
    return (
        "\n\nYou have access to the following tools:\n"
        f"{tool_lines}\n\n"
        "If you need one to complete this request, respond with EXACTLY one line in the form:\n"
        "TOOL_REQUEST: <tool_name> <JSON args>\n"
        "Otherwise, produce the final artifact directly, with no TOOL_REQUEST line."
    )


def _run_specialist(specialist_id, title, mission, request_text, memory_context, permissions, task_id, feedback=None):
    """Run one specialist turn. If the specialist's first reply is a
    TOOL_REQUEST, the requested tool is executed exactly once and the
    specialist is asked to produce its final artifact using the tool's
    result -- capped at one tool call per turn, the same bounded-retry
    shape already used for QA revisions."""
    capability = EXECUTION_CAPABILITY[specialist_id]
    context_block = ""
    if memory_context:
        context_block = "Prior context from this company's memory:\n" + "\n".join(f"- {m}" for m in memory_context) + "\n\n"
    revision_block = f"\n\nA QA reviewer asked for a revision: {feedback}\nProduce a corrected version." if feedback else ""
    prompt = (
        f"You are the {title} at a digital company. Mission: {mission}\n\n"
        f"{_today_line()}"
        f"{context_block}"
        f"Fulfil this request from the Owner as a clear, complete artifact:\n\n{request_text}"
        f"{revision_block}"
        f"{_tool_prompt_block(permissions)}"
    )

    text, in_tok, out_tok, cost = model_provider.complete(capability, prompt)
    tool_events = []
    artifacts = []

    # The model is asked to reply with only a TOOL_REQUEST line, but in
    # practice sometimes prefixes it with a sentence of commentary -- scan
    # every line rather than trusting the reply is exactly one line.
    tool_line = next(
        (line.strip() for line in text.splitlines() if line.strip().startswith("TOOL_REQUEST:")), None
    )
    if tool_line:
        tool_result_text, event_detail, artifact = _execute_tool_request(tool_line, permissions, task_id)
        tool_events.append({"step": "tool_use", "employee": specialist_id, "detail": event_detail})
        if artifact:
            artifacts.append(artifact)

        followup_prompt = (
            f"{prompt}\n\n"
            f"You requested: {tool_line}\nTool result:\n{tool_result_text}\n\n"
            "Now produce the final artifact for the Owner using this result. Do not request another tool."
        )
        text, in_tok2, out_tok2, cost2 = model_provider.complete(capability, followup_prompt)
        in_tok += in_tok2
        out_tok += out_tok2
        cost += cost2

    return text, in_tok, out_tok, cost, tool_events, artifacts


def _execute_tool_request(tool_request_line, permissions, task_id):
    """Parse a 'TOOL_REQUEST: <name> <json args>' line and run it through
    the Tool Framework. Never raises -- a bad request or a denied
    permission comes back as a tool result the specialist can react to,
    same as any other tool outcome. Returns (result_text, event_detail,
    artifact_or_None) -- artifact is filled in only for a successful
    create_document call, so the UI can offer it as a download."""
    try:
        _, rest = tool_request_line.split(":", 1)
        parts = rest.strip().split(" ", 1)
        tool_name = parts[0].strip()
        args = json.loads(parts[1]) if len(parts) > 1 and parts[1].strip() else {}
        result = tools.call_tool(permissions, tool_name, context={"task_id": task_id}, **args)
        tool_def = tools.TOOLS.get(tool_name, {})
        artifact = {"filename": args["filename"]} if tool_def.get("produces_artifact") and "filename" in args else None
        return result, f"Used tool '{tool_name}' with args {args}.", artifact
    except (tools.ToolError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return f"Tool error: {exc}", f"Tool request '{tool_request_line}' failed: {exc}", None


def _run_qa(request_text, draft_text):
    qa_prompt = (
        "You are the QA Reviewer at a digital company.\n\n"
        f"{_today_line()}"
        f"Original request:\n{request_text}\n\nDraft:\n{draft_text}\n\n"
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
    draft_text, w_in, w_out, w_cost, w_tool_events, artifacts = _run_specialist(
        specialist_id, roster["title"], roster["mission"], request_text, memory_context, roster["permissions"], task_id
    )
    total_in += w_in
    total_out += w_out
    total_cost += w_cost
    timeline.append({"step": "execution", "employee": specialist_id, "detail": f"Drafted a response as {roster['title']}."})
    timeline.extend(w_tool_events)

    # QA
    store.update_task_status(task_id, "qa")
    store.set_employee_status("qa", "assigned")
    qa_note, q_in, q_out, q_cost = _run_qa(request_text, draft_text)
    total_in += q_in
    total_out += q_out
    total_cost += q_cost
    timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})

    if qa_note.strip().upper().startswith("REVISE"):
        draft_text, r_in, r_out, r_cost, r_tool_events, r_artifacts = _run_specialist(
            specialist_id, roster["title"], roster["mission"], request_text, memory_context,
            roster["permissions"], task_id, feedback=qa_note,
        )
        total_in += r_in
        total_out += r_out
        total_cost += r_cost
        timeline.append({"step": "revision", "employee": specialist_id, "detail": "Produced a corrected draft based on QA feedback."})
        timeline.extend(r_tool_events)
        artifacts.extend(r_artifacts)

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
        artifacts=artifacts,
    )

    # Memory Update
    store.create_memory_entry(
        task_id, summary=f"Task #{task_id} ({roster['title']}): {request_text[:120]!r} -> delivered."
    )
