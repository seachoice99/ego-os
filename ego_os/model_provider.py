import math
import os

from openai import OpenAI

from ego_os import store

# Capability -> concrete model + pricing (USD per token). Adding a second
# provider or model means adding entries/branches here; callers never change.
# ADR-0016/architecture/001 (Model Adapter, "partial"): every capability
# below currently resolves to the same single model -- real multi-dimensional
# selection (quality tier/latency/context/modality/availability/privacy) is a
# named, not-yet-built gap, not something this dict pretends to do.
_CAPABILITY_MODELS = {
    "business_communication": "anthropic/claude-haiku-4.5",
    "critique": "anthropic/claude-haiku-4.5",
    "delegation": "anthropic/claude-haiku-4.5",
    "synthesis": "anthropic/claude-haiku-4.5",
    "coding": "anthropic/claude-haiku-4.5",
    "cost_accounting": "anthropic/claude-haiku-4.5",
    "presentation_design": "anthropic/claude-haiku-4.5",
}

_PRICE_PER_TOKEN = {
    "anthropic/claude-haiku-4.5": {"input": 1.0 / 1_000_000, "output": 5.0 / 1_000_000},
}

# A deliberately generous, conservative proxy for "how many input tokens
# might this prompt cost" -- used only to size a pre-call RESERVATION
# (ADR-0016 step 1: "determine a conservative maximum, never optimistic"),
# never as a substitute for the real, provider-reported usage this module
# already records after the call.
_CHARS_PER_TOKEN_ESTIMATE = 4
_INPUT_TOKEN_SAFETY_BUFFER = 500

_client = None


class ModelSelectionError(Exception):
    """Fail-closed replacement for the previous unhandled KeyError: raised
    for an unmapped capability or a model with no recorded price. ADR-0016:
    unknown pricing is never treated as zero cost, and an unmapped
    capability/model must never silently proceed."""


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
    return _client


def model_for_capability(capability: str) -> str:
    """Exposed for execution-event logging (v0.4.1): which model actually
    served a given capability, without changing complete()'s return
    signature for every existing caller."""
    try:
        return _CAPABILITY_MODELS[capability]
    except KeyError:
        raise ModelSelectionError(f"unknown capability: {capability!r}") from None


def _resolve_model_and_price(capability):
    if capability not in _CAPABILITY_MODELS:
        raise ModelSelectionError(f"unknown capability: {capability!r}")
    model = _CAPABILITY_MODELS[capability]
    if model not in _PRICE_PER_TOKEN:
        raise ModelSelectionError(f"no recorded price for model: {model!r} (capability {capability!r})")
    return model, _PRICE_PER_TOKEN[model]


def _conservative_reservation_cents(prompt, max_tokens, price):
    estimated_input_tokens = len(prompt) // _CHARS_PER_TOKEN_ESTIMATE + _INPUT_TOKEN_SAFETY_BUFFER
    estimated_usd = estimated_input_tokens * price["input"] + max_tokens * price["output"]
    return math.ceil(estimated_usd * 100)  # always round UP -- a conservative ceiling, never an optimistic one


def complete(capability: str, prompt: str, max_tokens: int = 1024, task_id=None, task_budget_cents=None):
    """Given a required capability and a prompt, return
    (text, input_tokens, output_tokens, cost). The caller never knows or
    cares which provider/model actually served the request.

    ADR-0016: when task_id is given, this reserves a conservative maximum
    against the task's own sub-limit (if task_budget_cents is given) and
    the global operating budget BEFORE making the call, records the real
    measured spend afterward, and releases whatever portion of the
    reservation went unused. Raises store.BudgetError (never silently
    proceeds) if the reservation would exceed either limit -- callers
    (ego_os/lifecycle.py) are expected to catch this and move the
    ProductTask to a real, reported terminal state, never let it crash
    uncaught. task_id=None (e.g. a capability check with no ProductTask
    context) skips enforcement entirely -- unchanged, pre-ADR-0016 behavior."""
    model, price = _resolve_model_and_price(capability)

    reserved_cents = None
    if task_id is not None:
        reserved_cents = _conservative_reservation_cents(prompt, max_tokens, price)
        store.reserve_budget(
            task_id, reserved_cents, task_budget_cents=task_budget_cents,
            detail=f"capability={capability} model={model} max_tokens={max_tokens}",
        )

    response = _get_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cost = input_tokens * price["input"] + output_tokens * price["output"]

    if task_id is not None:
        actual_cents = math.ceil(cost * 100)  # round up here too -- never let rounding quietly under-report spend
        store.record_spend(task_id, actual_cents, detail=f"capability={capability} model={model}")
        store.release_reservation(task_id, max(0, reserved_cents - actual_cents), detail="unused portion of the pre-call reservation")

    return text, input_tokens, output_tokens, cost
