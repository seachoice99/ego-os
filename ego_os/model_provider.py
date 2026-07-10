import os

from openai import OpenAI

# Capability -> concrete model + pricing (USD per token). Adding a second
# provider or model means adding entries/branches here; callers never change.
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

_client = None


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
    return _CAPABILITY_MODELS[capability]


def complete(capability: str, prompt: str, max_tokens: int = 1024):
    """Given a required capability and a prompt, return
    (text, input_tokens, output_tokens, cost). The caller never knows or
    cares which provider/model actually served the request."""
    model = _CAPABILITY_MODELS[capability]
    response = _get_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    input_tokens = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    price = _PRICE_PER_TOKEN[model]
    cost = input_tokens * price["input"] + output_tokens * price["output"]
    return text, input_tokens, output_tokens, cost
