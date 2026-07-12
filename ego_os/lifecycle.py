import json
import re
import time
from datetime import date

from ego_os import model_provider, skills, store, tools

_TOOL_REQUEST_RE = re.compile(r"TOOL_REQUEST:\s*(\S+)")


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _resolve_employee_skills(skill_refs, task_id=None, specialist_id=None):
    """skill_refs: the employee's roster `skills` list, each
    {"id": ..., "version": ...} (SR-02). Resolves each to its exact,
    locked manifest, failing closed (raising skills.SkillError -- a
    clean message, no stack trace) before any model call if a reference
    is missing, revoked, or tampered, per architecture/012: 'Missing/
    revoked/tampered Skill: fail before provider invocation.' An
    Employee with no skills (every pre-SR-02 Employee) resolves to an
    empty list and behaves exactly as before.

    A successful resolution is genuine operational validation (SR-04
    quality follow-up) -- the manifest was actually loaded and its
    entrypoint digest actually checked -- so it logs exactly one
    'validated' Skill audit event per resolved skill per task. Called
    once per task run and reused for any QA revision, so a revision
    never double-logs. This is deliberately *not* triggered by viewing
    the read-only /skills UI, which must never mutate the audit trail."""
    resolved = [skills.get_exact_version(ref["id"], ref["version"]) for ref in (skill_refs or [])]
    for manifest in resolved:
        store.log_skill_audit_event(
            manifest["id"], "validated", skill_version=manifest["version"],
            detail=f"Resolved for task #{task_id}, employee '{specialist_id}'.",
        )
    return resolved


def _skill_instructions_block(resolved_skills):
    """Render each resolved Skill's entrypoint content into a labeled
    prompt section (SR-03), read directly from its already
    digest-verified entrypoint file -- never re-interpreted or executed,
    just included as instruction text. Comes *after* the Persona framing
    ("You are the {title}... Mission: ...") in the prompt, never before
    it, so a Skill can shape *how* the work is reported without ever
    displacing *who* the specialist is or what it's accountable for."""
    if not resolved_skills:
        return ""
    blocks = []
    for manifest in resolved_skills:
        entrypoint_path = manifest["_package_dir"] / manifest["entrypoint"]["path"]
        instructions = entrypoint_path.read_text(encoding="utf-8")
        blocks.append(
            f"Follow this Skill ({manifest['id']}@{manifest['version']}) for how to structure "
            f"your work and final report:\n\n{instructions}"
        )
    return "\n\n".join(blocks) + "\n\n"


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
    "designer": "presentation_design",
}


def _select_specialist(request_text, task_id=None):
    """Orchestrator genuinely chooses between more than one specialist by
    required capability, instead of a fixed rule. Returns
    (specialist_id_or_None, gap_reason_or_None, in_tok, out_tok, cost) --
    specialist_id is None only when the model itself reports no existing
    roster member has the right capability (a genuine Capability Gap, v0.3),
    which is different from an ambiguous reply that still gets a safe
    default."""
    roster = store.get_roster_summary(list(EXECUTION_CAPABILITY.keys()))
    roster_description = "\n".join(
        f"- {r['id']}: {r['title']}. Mission: {r['mission']}. Capabilities: {', '.join(r['required_capabilities'])}."
        for r in roster
    )
    prompt = (
        "You are the Orchestrator at a digital company, deciding who should staff a task.\n\n"
        f"Available specialists:\n{roster_description}\n\n"
        f"Owner's request:\n{request_text}\n\n"
        "If one of these specialists can genuinely handle this request, reply with exactly one "
        "word: their id, nothing else.\n"
        "If none of them have the right capability for this request, reply with exactly:\n"
        "NO_MATCH: <one short sentence on what capability is missing>"
    )
    decision_text, in_tok, out_tok, cost = model_provider.complete("delegation", prompt, task_id=task_id)
    decision = decision_text.strip()
    if decision.upper().startswith("NO_MATCH"):
        gap_reason = decision.split(":", 1)[1].strip() if ":" in decision else "no matching capability"
        return None, gap_reason, in_tok, out_tok, cost
    decision_lower = decision.lower()
    for candidate_id in EXECUTION_CAPABILITY:
        if candidate_id in decision_lower:
            return candidate_id, None, in_tok, out_tok, cost
    return "writer", None, in_tok, out_tok, cost  # safe default if the reply was ambiguous


_PROPOSAL_FIELDS = (
    "title", "department", "mission", "responsibilities", "required_capabilities",
    "tools", "permissions", "reporting_rules", "temporary_or_permanent", "reason",
)


def _draft_employee_proposal(request_text, gap_reason, task_id=None):
    """Capability Gap Handling (v0.3): instead of silently defaulting to an
    existing specialist that doesn't really fit, draft an Employee Creation
    Proposal matching tasks/templates/EMPLOYEE_CREATION.md's shape, for the
    Owner to review. This only drafts the proposal -- it never creates the
    employee automatically (unattended employee creation is deferred)."""
    prompt = (
        "You are the Orchestrator at a digital company. No existing employee can handle this "
        f"request: {gap_reason}\n\nOwner's request:\n{request_text}\n\n"
        "Draft a proposal for a new employee to handle requests like this, matching this exact "
        "JSON shape (responsibilities/required_capabilities/tools/permissions/reporting_rules are "
        "arrays of short strings, everything else is a string):\n"
        '{"title": "...", "department": "...", "mission": "...", "responsibilities": ["..."], '
        '"required_capabilities": ["..."], "tools": ["..."], "permissions": ["..."], '
        '"reporting_rules": ["..."], "temporary_or_permanent": "temporary or permanent", '
        '"reason": "why existing employees are not enough"}\n\n'
        "Reply with ONLY that JSON object, nothing else."
    )
    text, in_tok, out_tok, cost = model_provider.complete("delegation", prompt, task_id=task_id)
    brace = text.find("{")
    fields = {}
    if brace != -1:
        try:
            fields = json.JSONDecoder().raw_decode(text[brace:])[0]
        except json.JSONDecodeError:
            fields = {}
    defaults = {
        "title": "Proposed Specialist", "department": "Unassigned", "mission": request_text[:200],
        "responsibilities": [], "required_capabilities": [], "tools": [], "permissions": [],
        "reporting_rules": [], "temporary_or_permanent": "temporary", "reason": gap_reason,
    }
    for field in _PROPOSAL_FIELDS:
        fields.setdefault(field, defaults[field])
    return fields, in_tok, out_tok, cost


def _attachment_line(task_id):
    """Whether a file was actually attached to this task is a fact the
    server already knows -- the specialist shouldn't have to guess it from
    the wording of the request. Found live: a specialist sometimes assumed
    no attachment existed and told the Owner to attach one without ever
    attempting the tool call, even when a real file was uploaded and
    present on disk."""
    upload_dir = tools.UPLOADS_DIR / str(task_id)
    if upload_dir.is_dir():
        names = sorted(p.name for p in upload_dir.iterdir() if p.suffix.lower() in (".zip", ".pdf"))
        if names:
            return f"Fact: an attachment was provided for this task: {', '.join(names)}.\n\n"
    return "Fact: no file attachment was provided for this task.\n\n"


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


def _run_specialist(specialist_id, title, mission, request_text, memory_context, permissions, task_id, resolved_skills=None, feedback=None):
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
    # Only relevant for a specialist whose tools actually consume an
    # upload -- stating it for everyone else would just be noise.
    attachment_block = _attachment_line(task_id) if "build_presentation_sites" in permissions else ""
    skill_block = _skill_instructions_block(resolved_skills)
    prompt = (
        f"You are the {title} at a digital company. Mission: {mission}\n\n"
        f"{_today_line()}"
        f"{attachment_block}"
        f"{context_block}"
        f"{skill_block}"
        f"Fulfil this request from the Owner as a clear, complete artifact:\n\n{request_text}"
        f"{revision_block}"
        f"{_tool_prompt_block(permissions)}"
    )

    text, in_tok, out_tok, cost = model_provider.complete(capability, prompt, task_id=task_id)
    tool_events = []
    artifacts = []

    # The model is asked to reply with only a TOOL_REQUEST line, but in
    # practice it sometimes prefixes commentary, spreads the JSON args
    # across multiple physical lines, or appends trailing text after the
    # closing brace -- found live in production (a "content" argument
    # containing a real multi-line script broke a strict single-line
    # json.loads with "Extra data"). Search the whole reply for the marker
    # and parse only the first valid JSON value after it, ignoring anything
    # before or after that one value.
    match = _TOOL_REQUEST_RE.search(text)
    if match:
        tool_result_text, event_info, artifact = _execute_tool_request(text, match, permissions, task_id)
        tool_events.append({"step": "tool_use", "employee": specialist_id, **event_info})
        if artifact:
            artifacts.append(artifact)

        followup_prompt = (
            f"{prompt}\n\n"
            f"You requested: {match.group(0)}\nTool result:\n{tool_result_text}\n\n"
            "Now produce the final artifact for the Owner using this result. Do not request another tool."
        )
        text, in_tok2, out_tok2, cost2 = model_provider.complete(capability, followup_prompt, task_id=task_id)
        in_tok += in_tok2
        out_tok += out_tok2
        cost += cost2

    return text, in_tok, out_tok, cost, tool_events, artifacts


def _execute_tool_request(text, match, permissions, task_id):
    """Parse a 'TOOL_REQUEST: <name> <json args>' marker found anywhere in
    text and run it through the Tool Framework. Never raises -- a bad
    request or a denied permission comes back as a tool result the
    specialist can react to, same as any other tool outcome. Returns
    (result_text, event_info, artifact_or_None) -- event_info is a dict
    with the fields execution-event logging needs (detail, tool_name, a
    JSON-serialized args summary, and status); artifact is filled in only
    for a successful call to a tool marked produces_artifact, with an
    explicit `type` (e.g. "document", "spreadsheet") taken from the tool's
    registry entry rather than guessed from the filename, so the UI can
    offer it as a typed, downloadable artifact."""
    tool_name = match.group(1)
    remainder = text[match.end():].strip()
    try:
        args = json.JSONDecoder().raw_decode(remainder)[0] if remainder else {}
        result = tools.call_tool(permissions, tool_name, context={"task_id": task_id}, **args)
        tool_def = tools.TOOLS.get(tool_name, {})
        artifact_type = tool_def.get("produces_artifact")
        if artifact_type == "website" and "site_name" in args:
            artifact = {"type": "website", "site_name": args["site_name"], "url": f"/p/{args['site_name']}/"}
        elif artifact_type and "filename" in args:
            artifact = {"type": artifact_type, "filename": args["filename"]}
        else:
            artifact = None
        event_info = {
            "detail": f"Used tool '{tool_name}' with args {args}.",
            "tool_name": tool_name,
            "tool_args_summary": json.dumps(args),
            "status": "ok",
        }
        return result, event_info, artifact
    except (tools.ToolError, ValueError, TypeError, json.JSONDecodeError) as exc:
        event_info = {
            "detail": f"Tool request for '{tool_name}' failed: {exc}",
            "tool_name": tool_name,
            "tool_args_summary": None,
            "status": "error",
        }
        return f"Tool error: {exc}", event_info, None


def _run_qa(request_text, draft_text, task_id=None):
    qa_prompt = (
        "You are the QA Reviewer at a digital company.\n\n"
        f"{_today_line()}"
        f"Original request:\n{request_text}\n\nDraft:\n{draft_text}\n\n"
        "Reply with PASS if the draft satisfies the request, or REVISE: <reason> if not."
    )
    return model_provider.complete("critique", qa_prompt, task_id=task_id)


def _classify_qa_verdict(qa_note):
    """ADR-0014: a verdict is 'pass', 'revise', or -- anything else --
    'malformed'. Malformed is never silently treated as either of the
    other two; it fails closed to needs_owner_review exactly like a
    second REVISE does."""
    upper = (qa_note or "").strip().upper()
    if upper.startswith("PASS"):
        return "pass"
    if upper.startswith("REVISE"):
        return "revise"
    return "malformed"


def run(task_id: int, project_id: int, request_text: str):
    """Run the documented Task Lifecycle for one task:
    Intake -> Planning -> Staffing -> Execution -> QA -> Delivery -> Memory Update.

    QA is a real gate: a REVISE verdict sends the draft back for exactly
    one corrected attempt before delivery, rather than being recorded and
    ignored.

    Every significant step is also written to execution_events (v0.4.1)
    as it happens, incrementally -- unlike reports.timeline (still built
    here too, unchanged, for backward-compatible rendering), which is
    only ever written once, at the very end. A crash mid-task now leaves
    a real, queryable operational record instead of nothing."""
    timeline = []
    total_in = total_out = 0
    total_cost = 0.0

    meta_roster = {r["id"]: r for r in store.get_roster_summary(["orchestrator", "qa"])}
    orchestrator_version = meta_roster.get("orchestrator", {}).get("version")
    qa_version = meta_roster.get("qa", {}).get("version")

    # Intake
    timeline.append({"step": "intake", "employee": "orchestrator", "detail": "Received request from Owner."})
    store.log_execution_event(
        task_id, step="intake", employee_id="orchestrator", employee_version=orchestrator_version,
        status="ok", detail="Received request from Owner.",
    )

    # Planning
    store.update_task_status(task_id, "planning")
    store.set_employee_status("orchestrator", "assigned")
    memory_context = store.get_recent_memory(project_id)
    timeline.append({"step": "planning", "employee": "orchestrator", "detail": "Reviewed request and prior project memory."})
    store.log_execution_event(
        task_id, step="planning", employee_id="orchestrator", employee_version=orchestrator_version,
        status="ok", detail="Reviewed request and prior project memory.",
    )

    # Staffing
    store.update_task_status(task_id, "staffing")
    staffing_start = time.perf_counter()
    specialist_id, gap_reason, s_in, s_out, s_cost = _select_specialist(request_text, task_id=task_id)
    staffing_duration_ms = _elapsed_ms(staffing_start)
    total_in += s_in
    total_out += s_out
    total_cost += s_cost

    if specialist_id is None:
        # Capability Gap Handling (v0.3): a genuine gap surfaces an
        # Owner-actionable Employee Creation Proposal and pauses the task,
        # instead of silently defaulting to a specialist who doesn't fit.
        timeline.append({
            "step": "staffing", "employee": "orchestrator",
            "detail": f"No existing specialist matches this request: {gap_reason}",
        })
        store.log_execution_event(
            task_id, step="staffing", employee_id="orchestrator", employee_version=orchestrator_version,
            capability="delegation", model=model_provider.model_for_capability("delegation"),
            input_tokens=s_in, output_tokens=s_out, cost=s_cost, status="gap",
            detail=f"No existing specialist matches this request: {gap_reason}",
            duration_ms=staffing_duration_ms,
        )
        proposal_start = time.perf_counter()
        fields, p_in, p_out, p_cost = _draft_employee_proposal(request_text, gap_reason, task_id=task_id)
        proposal_duration_ms = _elapsed_ms(proposal_start)
        total_in += p_in
        total_out += p_out
        total_cost += p_cost
        store.create_employee_proposal(
            task_id=task_id, trigger_text=request_text, title=fields["title"],
            department=fields["department"], mission=fields["mission"],
            responsibilities=fields["responsibilities"],
            required_capabilities=fields["required_capabilities"],
            tools_=fields["tools"], permissions=fields["permissions"],
            reporting_rules=fields["reporting_rules"],
            temporary_or_permanent=fields["temporary_or_permanent"], reason=fields["reason"],
            input_tokens=total_in, output_tokens=total_out, cost=total_cost,
        )
        timeline.append({
            "step": "gap", "employee": "orchestrator",
            "detail": f"Drafted an Employee Creation Proposal ({fields['title']}) for Owner review.",
        })
        store.log_execution_event(
            task_id, step="gap", employee_id="orchestrator", employee_version=orchestrator_version,
            capability="delegation", model=model_provider.model_for_capability("delegation"),
            input_tokens=p_in, output_tokens=p_out, cost=p_cost, status="ok",
            detail=f"Drafted an Employee Creation Proposal ({fields['title']}) for Owner review.",
            duration_ms=proposal_duration_ms,
        )
        store.update_task_status(task_id, "awaiting_approval")
        store.set_employee_status("orchestrator", "idle")
        return

    roster = store.get_roster_summary([specialist_id])[0]
    timeline.append({"step": "staffing", "employee": "orchestrator", "detail": f"Assigned {roster['title']} and QA Reviewer."})
    store.log_execution_event(
        task_id, step="staffing", employee_id="orchestrator", employee_version=orchestrator_version,
        capability="delegation", model=model_provider.model_for_capability("delegation"),
        input_tokens=s_in, output_tokens=s_out, cost=s_cost, status="ok",
        detail=f"Assigned {roster['title']} and QA Reviewer.", duration_ms=staffing_duration_ms,
    )
    employee_versions = {"orchestrator": orchestrator_version, specialist_id: roster["version"], "qa": qa_version}
    specialist_capability = EXECUTION_CAPABILITY[specialist_id]

    # Skill resolution (SR-02): resolved once, before the specialist is
    # ever invoked -- a missing/revoked/tampered reference fails closed
    # right here, propagating up through worker.process_one as a clean
    # 'failed' task, never reaching a model call.
    try:
        resolved_skills = _resolve_employee_skills(roster.get("skills", []), task_id=task_id, specialist_id=specialist_id)
    except skills.SkillError as exc:
        store.log_execution_event(
            task_id, step="skill_resolution", employee_id=specialist_id, employee_version=roster["version"],
            status="error", detail=str(exc),
        )
        employee_skill_refs = roster.get("skills") or [{}]
        store.log_skill_audit_event(
            employee_skill_refs[0].get("id") or "unknown",
            "resolution_failure",
            skill_version=employee_skill_refs[0].get("version"),
            detail=f"Task #{task_id}, employee '{specialist_id}': {exc}",
        )
        # ADR-0014: every terminal ProductTask state gets a Report -- a
        # Skill-resolution failure previously left the task stuck at
        # status="staffing" with no report at all. still re-raised so
        # worker.process_one's own run_state="failed" bookkeeping is
        # unaffected -- this only ensures the ProductTask's own lifecycle
        # status and Report are correct before that happens.
        timeline.append({"step": "skill_resolution", "employee": specialist_id, "detail": f"Skill resolution failed: {exc}"})
        store.update_task_status(
            task_id, "failed", terminal_reason={"category": "tool_failure", "detail": f"Skill resolution failed: {exc}"},
        )
        store.create_report(
            task_id=task_id, employees_involved=["orchestrator", specialist_id],
            timeline=timeline, input_tokens=total_in, output_tokens=total_out, cost=total_cost,
            result_text=None, qa_note=None, employee_versions={"orchestrator": orchestrator_version, specialist_id: roster["version"]},
            terminal_status="failed", terminal_reason={"category": "tool_failure", "detail": f"Skill resolution failed: {exc}"},
        )
        store.set_employee_status("orchestrator", "idle")
        raise
    primary_skill = resolved_skills[0] if resolved_skills else None
    skill_id = primary_skill["id"] if primary_skill else None
    skill_version = primary_skill["version"] if primary_skill else None
    skill_digest = primary_skill["entrypoint"]["digest"] if primary_skill else None
    skills_used = [
        {"id": m["id"], "version": m["version"], "digest": m["entrypoint"]["digest"]} for m in resolved_skills
    ]

    # Execution
    store.update_task_status(task_id, "execution")
    store.set_employee_status(specialist_id, "assigned")
    execution_start = time.perf_counter()
    draft_text, w_in, w_out, w_cost, w_tool_events, artifacts = _run_specialist(
        specialist_id, roster["title"], roster["mission"], request_text, memory_context, roster["permissions"], task_id,
        resolved_skills=resolved_skills,
    )
    execution_duration_ms = _elapsed_ms(execution_start)
    total_in += w_in
    total_out += w_out
    total_cost += w_cost
    timeline.append({"step": "execution", "employee": specialist_id, "detail": f"Drafted a response as {roster['title']}."})
    store.log_execution_event(
        task_id, step="execution", employee_id=specialist_id, employee_version=roster["version"],
        capability=specialist_capability, model=model_provider.model_for_capability(specialist_capability),
        input_tokens=w_in, output_tokens=w_out, cost=w_cost, status="ok",
        detail=f"Drafted a response as {roster['title']}.", duration_ms=execution_duration_ms,
        skill_id=skill_id, skill_version=skill_version, skill_digest=skill_digest,
    )
    for event in w_tool_events:
        timeline.append({"step": event["step"], "employee": event["employee"], "detail": event["detail"]})
        store.log_execution_event(
            task_id, step="tool_use", employee_id=specialist_id, employee_version=roster["version"],
            tool_name=event.get("tool_name"), tool_args_summary=event.get("tool_args_summary"),
            status=event.get("status"), detail=event["detail"],
        )

    # QA (ADR-0014: QA is a real gate -- see architecture/002_TASK_LIFECYCLE.md's
    # transition table. PASS delivers; REVISE gets exactly one automatic
    # retry; a second REVISE or any malformed verdict (either call) fails
    # closed to needs_owner_review, never silently delivered.)
    store.update_task_status(task_id, "qa")
    store.set_employee_status("qa", "assigned")
    qa_start = time.perf_counter()
    qa_note, q_in, q_out, q_cost = _run_qa(request_text, draft_text, task_id=task_id)
    qa_duration_ms = _elapsed_ms(qa_start)
    total_in += q_in
    total_out += q_out
    total_cost += q_cost
    first_verdict = _classify_qa_verdict(qa_note)
    timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})
    store.log_execution_event(
        task_id, step="qa", employee_id="qa", employee_version=qa_version,
        capability="critique", model=model_provider.model_for_capability("critique"),
        input_tokens=q_in, output_tokens=q_out, cost=q_cost, status=first_verdict,
        detail=qa_note, duration_ms=qa_duration_ms,
    )

    if first_verdict == "malformed":
        store.set_employee_status(specialist_id, "idle")
        store.set_employee_status("qa", "idle")
        reason = {"category": "qa_failed", "detail": f"Malformed QA verdict on first review: {qa_note!r}"}
        timeline.append({"step": "needs_owner_review", "employee": "qa", "detail": reason["detail"]})
        store.update_task_status(task_id, "needs_owner_review", terminal_reason=reason)
        store.set_employee_status("orchestrator", "idle")
        store.create_report(
            task_id=task_id, employees_involved=["orchestrator", specialist_id, "qa"], timeline=timeline,
            input_tokens=total_in, output_tokens=total_out, cost=total_cost, result_text=draft_text,
            qa_note=qa_note, artifacts=artifacts, employee_versions=employee_versions, skills_used=skills_used,
            terminal_status="needs_owner_review", terminal_reason=reason,
        )
        return

    if first_verdict == "revise":
        store.update_task_status(task_id, "revision")
        revision_start = time.perf_counter()
        draft_text, r_in, r_out, r_cost, r_tool_events, r_artifacts = _run_specialist(
            specialist_id, roster["title"], roster["mission"], request_text, memory_context,
            roster["permissions"], task_id, resolved_skills=resolved_skills, feedback=qa_note,
        )
        revision_duration_ms = _elapsed_ms(revision_start)
        total_in += r_in
        total_out += r_out
        total_cost += r_cost
        timeline.append({"step": "revision", "employee": specialist_id, "detail": "Produced a corrected draft based on QA feedback."})
        store.log_execution_event(
            task_id, step="revision", employee_id=specialist_id, employee_version=roster["version"],
            capability=specialist_capability, model=model_provider.model_for_capability(specialist_capability),
            input_tokens=r_in, output_tokens=r_out, cost=r_cost, status="ok",
            detail="Produced a corrected draft based on QA feedback.", duration_ms=revision_duration_ms,
            skill_id=skill_id, skill_version=skill_version, skill_digest=skill_digest,
        )
        for event in r_tool_events:
            timeline.append({"step": event["step"], "employee": event["employee"], "detail": event["detail"]})
            store.log_execution_event(
                task_id, step="tool_use", employee_id=specialist_id, employee_version=roster["version"],
                tool_name=event.get("tool_name"), tool_args_summary=event.get("tool_args_summary"),
                status=event.get("status"), detail=event["detail"],
            )
        # The revision is a full redo of the same request, not an addition to
        # it -- if it produced its own artifacts, those replace the pre-revision
        # ones instead of accumulating alongside them (found live: a revised
        # tool-using task showed two duplicate artifact cards for the same file).
        if r_artifacts:
            artifacts = r_artifacts

        store.update_task_status(task_id, "qa")
        qa2_start = time.perf_counter()
        qa_note, q2_in, q2_out, q2_cost = _run_qa(request_text, draft_text, task_id=task_id)
        qa2_duration_ms = _elapsed_ms(qa2_start)
        total_in += q2_in
        total_out += q2_out
        total_cost += q2_cost
        second_verdict = _classify_qa_verdict(qa_note)
        timeline.append({"step": "qa", "employee": "qa", "detail": qa_note})
        store.log_execution_event(
            task_id, step="qa", employee_id="qa", employee_version=qa_version,
            capability="critique", model=model_provider.model_for_capability("critique"),
            input_tokens=q2_in, output_tokens=q2_out, cost=q2_cost, status=second_verdict,
            detail=qa_note, duration_ms=qa2_duration_ms,
        )

        if second_verdict != "pass":
            store.set_employee_status(specialist_id, "idle")
            store.set_employee_status("qa", "idle")
            detail = (
                f"Malformed QA verdict on second review: {qa_note!r}" if second_verdict == "malformed"
                else f"QA still requested a revision on the second review: {qa_note}"
            )
            reason = {"category": "qa_failed", "detail": detail}
            timeline.append({"step": "needs_owner_review", "employee": "qa", "detail": detail})
            store.update_task_status(task_id, "needs_owner_review", terminal_reason=reason)
            store.set_employee_status("orchestrator", "idle")
            store.create_report(
                task_id=task_id, employees_involved=["orchestrator", specialist_id, "qa"], timeline=timeline,
                input_tokens=total_in, output_tokens=total_out, cost=total_cost, result_text=draft_text,
                qa_note=qa_note, artifacts=artifacts, employee_versions=employee_versions, skills_used=skills_used,
                terminal_status="needs_owner_review", terminal_reason=reason,
            )
            return

    store.set_employee_status(specialist_id, "idle")
    store.set_employee_status("qa", "idle")

    # Delivery
    store.update_task_status(task_id, "delivered")
    store.set_employee_status("orchestrator", "idle")
    timeline.append({"step": "delivery", "employee": "orchestrator", "detail": "Delivered result and report to Owner."})
    store.log_execution_event(
        task_id, step="delivery", employee_id="orchestrator", employee_version=orchestrator_version,
        status="ok", detail="Delivered result and report to Owner.",
    )

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
        employee_versions=employee_versions,
        skills_used=skills_used,
        terminal_status="delivered",
        terminal_reason=None,
    )

    # Memory Update
    store.create_memory_entry(
        task_id, summary=f"Task #{task_id} ({roster['title']}): {request_text[:120]!r} -> delivered."
    )
