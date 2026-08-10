## ADDED Requirements

### Requirement: Version metadata in every prompt module

Every module that contains a system prompt (Agent prompts, instruction boundary, agent robustness, output spec) SHALL declare `PROMPT_VERSION`, `PROMPT_UPDATED`, and `PROMPT_CHANGELOG` constants at the module level.

#### Scenario: Version constants are present in brand_bd agent
- **WHEN** importing `app.agents.brand_bd`
- **THEN** `brand_bd.PROMPT_VERSION` returns a semver string (e.g., "2.0.0")
- **AND** `brand_bd.PROMPT_UPDATED` returns an ISO date string (e.g., "2026-05-29")
- **AND** `brand_bd.PROMPT_CHANGELOG` returns a changelog string describing version history

#### Scenario: New prompt module automatically gets version metadata
- **WHEN** a new prompt-related module is created
- **THEN** it SHALL include version=1.0.0, updated=today, changelog="(初始版本)"

### Requirement: Runtime prompt registry

The system SHALL maintain a runtime `PromptRegistry` that collects version metadata from all prompt modules at import time and exposes it via a query API.

#### Scenario: Registry collects all prompt versions at startup
- **WHEN** the application starts and imports `agent.py`
- **THEN** `_auto_register_prompt_versions()` executes and registers all 11 prompt modules into `PromptRegistry`
- **AND** `PromptRegistry.list_all()` returns entries for all 11 modules

#### Scenario: Registry query by agent key
- **WHEN** calling `PromptRegistry.get("brand_bd")`
- **THEN** a `PromptMeta` object is returned with agent_key, display_name, version, updated, changelog, and prompt_length

### Requirement: Prompt version query API endpoint

The system SHALL expose an admin API endpoint that returns the current version summary of all prompt modules.

#### Scenario: Admin queries prompt versions
- **WHEN** a GET request is sent to `/admin/prompts/versions`
- **THEN** a JSON response is returned containing a map of agent keys to their version, update date, and prompt length
- **AND** the response includes a total count of registered modules

#### Scenario: API response includes all modules
- **WHEN** calling the versions endpoint
- **THEN** the response includes entries for all 8 agents, agent_robustness, output_spec, and instruction_boundary

### Requirement: Placeholder variable substitution

The system SHALL provide a `PromptLoader.fill_placeholders()` utility that replaces `{{key}}` style placeholders in template strings with provided values.

#### Scenario: Template variable is replaced
- **WHEN** `PromptLoader.fill_placeholders("品牌: {{brand}}, 品类: {{category}}", brand="XX美妆", category="护肤")` is called
- **THEN** the result is "品牌: XX美妆, 品类: 护肤"

#### Scenario: Missing placeholder is replaced with empty string
- **WHEN** `PromptLoader.fill_placeholders("品牌: {{brand}}", brand=None)` is called
- **THEN** the result is "品牌: " without raising an exception