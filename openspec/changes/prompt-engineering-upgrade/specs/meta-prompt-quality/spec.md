## ADDED Requirements

### Requirement: Shared meta-prompt standards module

The system SHALL provide a shared `meta_prompt_standards.py` module containing role definitions, analysis constraints, and output format templates for use by all LLM-analyzing-LLM Meta Prompts.

#### Scenario: Meta analyst role is defined
- **WHEN** `META_ANALYST_ROLE` is referenced from `meta_prompt_standards`
- **THEN** it defines the LLM's identity as a senior AI system analyst reviewing real agent performance data

#### Scenario: Meta constraints include confidence calibration
- **WHEN** `META_CONSTRAINTS` is injected into a Meta Prompt
- **THEN** it requires confidence_score ≤ 0.3 when sample count is below 5 or patterns are unclear

#### Scenario: Meta constraints require actionable suggestions
- **WHEN** `META_CONSTRAINTS` is injected into a Meta Prompt
- **THEN** it requires suggestions to be at the phrasing level, not generic quality improvement statements

### Requirement: Evolution suggester Meta Prompt quality

The `_call_llm_for_suggestions()` method in EvolutionSuggester SHALL use a structured Meta Prompt following the same engineering standards as business agent prompts.

#### Scenario: Suggestion Meta Prompt includes role and constraints
- **WHEN** `_call_llm_for_suggestions()` constructs the LLM prompt
- **THEN** the system message includes `META_ANALYST_ROLE`, `META_CONSTRAINTS`, `META_OUTPUT_FORMAT`, and a Few-shot example
- **AND** feedback data is sent as a separate HumanMessage

#### Scenario: Suggestion Meta Prompt uses proper JSON output
- **WHEN** the LLM responds to a suggestion analysis request
- **THEN** the response is parseable as JSON with `suggested_prompt_changes`, `knowledge_entries`, `analysis_summary`, and `confidence_score` fields

### Requirement: Single-result evolution analysis Meta Prompt quality

The `_call_llm_for_single_result()` method SHALL use a Meta Prompt with explicit single-sample confidence calibration.

#### Scenario: Single sample analysis caps confidence
- **WHEN** `_call_llm_for_single_result()` is called with one task result
- **THEN** the Meta Prompt explicitly instructs the LLM to set low confidence (≤ 0.35) and note sample limitation

### Requirement: Memory pattern extraction Meta Prompt quality

The `_extract_patterns()` method in ThreeLayerMemoryManager SHALL use a structured Meta Prompt with explicit pattern categorization and confidence based on frequency.

#### Scenario: Pattern extraction with frequency-based confidence
- **WHEN** `_extract_patterns()` calls the LLM for analysis
- **THEN** the Meta Prompt includes role definition, constraints, categorization rules, output format, and Few-shot examples
- **AND** confidence scoring rules are defined: ≥3 occurrences = 0.9, 2 = 0.7, 1 = 0.5

### Requirement: Prompt rule extraction Meta Prompt quality

The `_extract_prompt_rules()` method SHALL use a structured Meta Prompt that outputs rules with severity levels and trigger conditions.

#### Scenario: Rule extraction includes severity levels
- **WHEN** `_extract_prompt_rules()` calls the LLM for analysis
- **THEN** the output includes `level` field ("core" | "suggestion" | "nice_to_have") for each extracted rule
- **AND** each rule includes a `trigger` description of when it should activate

#### Scenario: Empty rules when no pattern is clear
- **WHEN** the memory data shows no consistent pattern
- **THEN** the Meta Prompt instructs the LLM to return an empty array rather than fabricating rules