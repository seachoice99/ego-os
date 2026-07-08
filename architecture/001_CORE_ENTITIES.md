# Core Entities

## Company

Digital organization owned by the user.

Fields:

- id
- name
- owner
- departments
- employees
- projects
- policies
- budget

## Employee

Replaceable competence container.

Fields:

- id
- name
- avatar
- title
- department
- mission
- responsibilities
- skills
- instructions
- required_capabilities
- tools
- permissions
- reporting_rules
- cost_policy
- version

## Project

Long-term context container.

Fields:

- id
- name
- status
- vision
- context
- decisions
- tasks
- artifacts
- memory

## Task

Unit of work.

Fields:

- id
- title
- user_request
- project_id
- status
- priority
- owner_employee
- assigned_employees
- plan
- logs
- result
- cost_report
- QA_report

## Report

Mandatory transparency object.

Fields:

- task_id
- employees_involved
- timeline
- decisions
- tools_used
- models_used
- token_usage
- cost
- outputs
- open_questions
