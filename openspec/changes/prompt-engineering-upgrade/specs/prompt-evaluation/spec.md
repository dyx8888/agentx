## ADDED Requirements

### Requirement: Test case definitions per agent

The system SHALL support YAML-based test case definitions per agent, each containing input, expected behaviors, and unacceptable behaviors.

#### Scenario: brand_bd test case file is loadable
- **WHEN** loading `tests/evaluation/cases/brand_bd.yaml`
- **THEN** a test suite is parsed with at least 3 cases
- **AND** each case has `id`, `description`, `input`, `expected_behaviors` (list), and `unacceptable` (list) fields

#### Scenario: KOL screening test case validates structured output
- **WHEN** the brand_bd KOL screening test case is loaded
- **THEN** `expected_behaviors` includes requirements for table format output, follower metrics, budget compliance, and recommendation rationale

### Requirement: LLM-as-Judge evaluation engine

The system SHALL provide a `judge.py` module that uses a structured LLM prompt to score agent outputs against test case criteria.

#### Scenario: Judge evaluates a passing output
- **WHEN** an agent output satisfies all `expected_behaviors` with no `unacceptable` hits
- **THEN** the judge returns `overall: "pass"` with score ≥ 6
- **AND** `behavior_scores` maps each expected behavior to 1 (satisfied)

#### Scenario: Judge detects unacceptable content
- **WHEN** an agent output contains content matching an `unacceptable` rule
- **THEN** the judge returns `unacceptable_hits` listing the matching rules
- **AND** the overall score is capped at 3 even if expected behaviors are met

#### Scenario: Judge handles unparseable LLM output
- **WHEN** the judge LLM returns content that cannot be parsed as JSON
- **THEN** the judge returns `overall: "fail"` with score 0 and a parse failure note
- **AND** does NOT throw an unhandled exception

### Requirement: Evaluation runner with report generation

The system SHALL provide a `runner.py` module that executes test cases against agents, invokes the judge, and generates evaluation reports.

#### Scenario: Full evaluation cycle for brand_bd
- **WHEN** `run_evaluation("brand_bd")` is called
- **THEN** all test cases from `brand_bd.yaml` are executed
- **AND** each output is evaluated by the judge
- **AND** a JSON report is written to `tests/evaluation/reports/`
- **AND** the report includes timestamp, prompt_version, total_cases, passed, failed, needs_review counts, and average_score

#### Scenario: Missing test case file returns error
- **WHEN** `run_evaluation("nonexistent_agent")` is called
- **THEN** an error dict is returned indicating the case file does not exist
- **AND** no exception is propagated

#### Scenario: Dry-run mode skips actual agent invocation
- **WHEN** `run_evaluation("brand_bd", dry_run=True)` is called
- **THEN** the evaluation pipeline runs but uses mock output instead of actual LLM invocation
- **AND** the report is still generated for pipeline validation

### Requirement: Judge system prompt follows best practices

The LLM-as-Judge system prompt SHALL follow the same prompt engineering standards applied to business agents.

#### Scenario: Judge prompt includes role and constraints
- **WHEN** the judge constructs its system message
- **THEN** it includes a role definition ("AI输出质量评判专家"), evaluation rules, scoring criteria, output format specification, and behavioral constraints

#### Scenario: Judge prompt uses structured scoring
- **WHEN** scoring agent outputs
- **THEN** each expected behavior is scored as 1 (satisfied) or 0 (not satisfied) — not a subjective numeric scale
- **AND** the overall quality score (0-10) follows a documented rubric with clear thresholds