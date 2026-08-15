"""Test DeepSeek API multi-channel failover functionality."""

import asyncio
import os
from types import SimpleNamespace

import pytest
import yaml

import app.services.model_gateway as model_gateway_module
from app.services.model_gateway import ModelApiKeyMissingError, ModelGateway


class TestDeepSeekFailover:
    """Test DeepSeek failover configuration and functionality."""

    def test_load_multi_channel_config(self):
        """正常场景1：正确加载多渠道配置"""
        # Load the config file directly
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "model_config.yaml"
        )

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Verify deepseek model has fallback_models
        deepseek_config = config["models"]["deepseek"]
        assert "fallback_models" in deepseek_config
        assert "deepseek_volc" in deepseek_config["fallback_models"]

        # Verify deepseek_volc model exists and has correct base_url
        deepseek_volc_config = config["models"]["deepseek_volc"]
        assert deepseek_volc_config is not None
        assert deepseek_volc_config["base_url"] == "https://ark.cn-beijing.volces.com/api/v3"
        assert deepseek_volc_config["model_name"] == "deepseek-chat"
        # 火山引擎（Volcengine）使用 OpenAI 兼容 API，provider 标识为 "volcano"
        assert deepseek_volc_config["provider"] == "volcano"

        print("✓ Multi-channel configuration loaded correctly")

    def test_create_llm_instances(self):
        """正常场景2：ModelGateway 能成功创建所有渠道的 LLM 实例"""
        # Set test environment variables
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        os.environ["DEEPSEEK_VOLC_API_KEY"] = "test-volc-key"

        try:
            gateway = ModelGateway()

            # Test creating deepseek model
            deepseek_llm = gateway.get_llm("deepseek")
            assert deepseek_llm is not None
            assert hasattr(deepseek_llm, "models")
            assert len(deepseek_llm.models) >= 1  # At least primary model

            # Test creating deepseek_volc model
            volc_llm = gateway.get_llm("deepseek_volc")
            assert volc_llm is not None
            assert hasattr(volc_llm, "models")
            assert len(volc_llm.models) >= 1  # At least primary model

            print("✓ LLM instances created successfully for both channels")

        except Exception as e:
            pytest.fail(f"Failed to create LLM instances: {e}")

    def test_missing_api_key_error(self):
        """异常场景1：备用渠道 API Key 缺失时抛出明确错误"""
        # 注意：ModelGateway.__init__ 会调用 load_dotenv() 从 .env 文件加载环境变量，
        # 直接 os.environ.pop 无法清除 .env 中的值。使用 mock 直接模拟 API Key 缺失。
        from unittest.mock import patch

        # Set deepseek key for primary model
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"

        try:
            gateway = ModelGateway()

            # mock _get_env_api_key 返回 None，模拟 API Key 缺失
            with patch.object(gateway, "_get_env_api_key", return_value=None):
                # This should raise ValueError for missing API key
                # get_llm -> FailoverChatModel.__init__ -> _init_models -> _create_model_instance
                with pytest.raises(ModelApiKeyMissingError) as exc_info:
                    gateway.get_llm("deepseek_volc")

                # Verify error message contains expected content
                error_message = str(exc_info.value)
                assert exc_info.value.code == "model_api_key_missing"
                assert "VOLCANO_API_KEY" in error_message
                assert exc_info.value.to_public_payload()["requires_config"] is True

            print("✓ Correct error raised for missing API key")

        except Exception as e:
            pytest.fail(f"Unexpected error: {e}")

    def test_nonexistent_fallback_model(self, tmp_path, monkeypatch):
        """Nonexistent fallback models are ignored without touching the real config."""
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        os.environ["DEEPSEEK_VOLC_API_KEY"] = "test-volc-key"
        monkeypatch.setattr(model_gateway_module, "load_dotenv", lambda *args, **kwargs: None)

        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "model_config.yaml"
        )
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        config["models"]["deepseek"].setdefault("fallback_models", []).append(
            "non_exist_model"
        )
        temp_config_path = tmp_path / "model_config.yaml"
        temp_config_path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        gateway = ModelGateway(config_path=str(temp_config_path))
        failover_model = gateway.get_llm("deepseek")

        assert failover_model is not None
        assert "non_exist_model" in failover_model.fallback_models
        assert len(failover_model.models) >= 1

    def test_master_react_missing_key_returns_error_not_fake_success(self):
        """缺模型 Key 时 master 不能把原始用户问题伪装成正常回答。"""
        from app.agents.master_router import MasterAgentRouter

        class MissingKeyGateway:
            def get_llm(self, *args, **kwargs):
                raise ModelApiKeyMissingError(
                    model_key="deepseek",
                    provider="deepseek",
                    env_keys=("DEEPSEEK_API_KEY",),
                )

        router = MasterAgentRouter(model_gateway=MissingKeyGateway())
        context = SimpleNamespace(
            raw_input="帮我生成达人邀约方案",
            rewritten_query="",
            rag_chunks=[],
            company_id="239",
            intent_entities={},
        )

        async def collect_events():
            return [event async for event in router._run_react(context)]

        events = asyncio.run(collect_events())
        assert any(
            event.get("type") == "error"
            and event.get("code") == "model_api_key_missing"
            for event in events
        )
        assert not any(event.get("type") == "result" for event in events)

    def teardown_method(self):
        """Clean up after tests"""
        # Restore environment variables if needed
        test_keys = ["DEEPSEEK_API_KEY", "DEEPSEEK_VOLC_API_KEY"]
        for key in test_keys:
            if key in os.environ and os.environ[key].startswith("test-"):
                del os.environ[key]
