"""
SkillRegistry robustness tests.

These tests use only temporary YAML files and never read production config,
environment files, credentials, or external services.
"""

import os
import sys

sys.path.insert(0, str(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from app.skills.registry import SkillMeta, SkillRegistry


@pytest.fixture(autouse=True)
def _reset_skill_registry(monkeypatch):
    instance = SkillRegistry()
    instance._skills = {}
    instance._loaded_contents.clear()
    instance._embedding_cache = {}
    instance._config_path = None
    monkeypatch.delenv("SKILLS_CONFIG", raising=False)
    monkeypatch.setattr(SkillRegistry, "_precompute_embeddings", lambda self: None)
    yield


def test_missing_config_fails_closed_without_clearing_existing_skills():
    registry = SkillRegistry()
    registry.register(
        SkillMeta(
            name="existing",
            agent_name="agent",
            title="Existing",
            description="Existing skill",
            trigger_keywords=["existing"],
            skill_path="skills/existing.md",
        )
    )

    result = registry.load_from_config("/path/that/does/not/exist/skills.yaml")

    assert result is False
    assert "existing" in registry._skills


def test_empty_yaml_fails_closed(tmp_path):
    config_path = tmp_path / "empty-skills.yaml"
    config_path.write_text("", encoding="utf-8")

    registry = SkillRegistry()

    assert registry.load_from_config(str(config_path)) is False
    assert registry._skills == {}


def test_invalid_yaml_fails_closed(tmp_path):
    config_path = tmp_path / "invalid-skills.yaml"
    config_path.write_text("skills: [unclosed", encoding="utf-8")

    registry = SkillRegistry()

    assert registry.load_from_config(str(config_path)) is False
    assert registry._skills == {}


def test_skills_config_env_var_overrides_default(monkeypatch, tmp_path):
    config_path = tmp_path / "skills.yaml"
    config_path.write_text(
        """
skills:
  - name: env_skill
    agent_name: agent
    title: Env Skill
    description: Loaded from env path
    trigger_keywords: [env]
    skill_path: skills/env.md
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SKILLS_CONFIG", str(config_path))

    registry = SkillRegistry()

    assert registry.load_from_config() is True
    assert registry._config_path == str(config_path)
    assert "env_skill" in registry._skills


def test_reload_failure_preserves_existing_skills_and_cache():
    registry = SkillRegistry()
    old_skill = SkillMeta(
        name="old_skill",
        agent_name="agent",
        title="Old",
        description="Old skill",
        trigger_keywords=["old"],
        skill_path="skills/old.md",
    )
    registry._skills = {"old_skill": old_skill}
    registry._embedding_cache = {"old_skill": [0.1, 0.2]}
    registry._loaded_contents = {"old_skill": "cached content"}
    registry._config_path = "/path/that/does/not/exist/skills.yaml"

    assert registry._reload() is False
    assert registry._skills == {"old_skill": old_skill}
    assert registry._embedding_cache == {"old_skill": [0.1, 0.2]}
    assert registry._loaded_contents == {"old_skill": "cached content"}
