# Model Selection Policy

## Principle

Employees should define required capabilities, not hard-coded providers.

## Selection factors

- task type;
- required quality;
- cost limit;
- latency requirement;
- context length;
- tool support;
- multimodal support;
- availability;
- privacy constraints.

## Example

Instead of:

model: GPT-5.5

Use:

required_capabilities:
  - high_quality_reasoning
  - long_context
  - structured_output
cost_priority: medium
latency_priority: low

Infrastructure maps this to the best available provider.
