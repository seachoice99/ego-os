# Employee Model

## Definition

Employee is a replaceable competence container, not a personality simulation.

An employee combines:

- name and avatar for UI clarity;
- title and department;
- mission;
- responsibilities;
- instructions;
- required capabilities;
- tools and permissions;
- reporting rules;
- cost policy;
- version.

## No career growth

Employees do not have RPG-style progression. They are updated through versioning:

- better instructions;
- new models;
- new tools;
- improved workflows;
- changed permissions.

## Versioning

Example:

- Lead Presentation Designer v1.0
- Lead Presentation Designer v1.1 — improved slide critique rules
- Lead Presentation Designer v2.0 — new model and Figma integration

## Creation of missing employees

When a task requires a capability that is missing, Orchestrator can:

1. create a temporary employee for this task;
2. propose a permanent employee;
3. automatically add the employee if company policy allows it.

## Boundaries

Employees reference tools and capabilities by name and requirement, never by credential. API keys, tokens and other secrets are Infrastructure-level resources, resolved at runtime — never part of an Employee Definition and never held by an employee.

An employee's permissions describe what it may attempt, not what it is guaranteed to be allowed to do. Every permitted action still passes through the company's current Gate Control tier — permissions are not an independent authority above it.
