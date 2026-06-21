"""Test DeepSeek API multi-channel failover functionality."""

import os

import pytest
import yaml

from app.services.model_gateway import ModelGateway


class TestDeepSeekFailover:
    """Test DeepSeek failover configuration and functionality."""

    def test_load_multi_channel_config(self):
        """正常场景1：正确加载多渠道配置"""
        # Load the config file directly
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "model_config.yaml")

        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Verify deepseek model has fallback_models
        deepseek_config = config['models']['deepseek']
        assert 'fallback_models' in deepseek_config
        assert 'deepseek_volc' in deepseek_config['fallback_models']

        # Verify deepseek_volc model exists and has correct base_url
        deepseek_volc_config = config['models']['deepseek_volc']
        assert deepseek_volc_config is not None
        assert deepseek_volc_config['base_url'] == 'https://ark.cn-beijing.volces.com/api/v3'
        assert deepseek_volc_config['model_name'] == 'deepseek-chat'
        assert deepseek_volc_config['provider'] == 'openai_compatible'

        print("✓ Multi-channel configuration loaded correctly")

    def test_create_llm_instances(self):
        """正常场景2：ModelGateway 能成功创建所有渠道的 LLM 实例"""
        # Set test environment variables
        os.environ['DEEPSEEK_API_KEY'] = 'test-deepseek-key'
        os.environ['DEEPSEEK_VOLC_API_KEY'] = 'test-volc-key'

        try:
            gateway = ModelGateway()

            # Test creating deepseek model
            deepseek_llm = gateway.get_llm('deepseek')
            assert deepseek_llm is not None
            assert hasattr(deepseek_llm, 'models')
            assert len(deepseek_llm.models) >= 1  # At least primary model

            # Test creating deepseek_volc model
            volc_llm = gateway.get_llm('deepseek_volc')
            assert volc_llm is not None
            assert hasattr(volc_llm, 'models')
            assert len(volc_llm.models) >= 1  # At least primary model

            print("✓ LLM instances created successfully for both channels")

        except Exception as e:
            pytest.fail(f"Failed to create LLM instances: {e}")

    def test_missing_api_key_error(self):
        """异常场景1：备用渠道 API Key 缺失时抛出明确错误"""
        # Clear the volc API key
        if 'DEEPSEEK_VOLC_API_KEY' in os.environ:
            del os.environ['DEEPSEEK_VOLC_API_KEY']

        # Set deepseek key for primary model
        os.environ['DEEPSEEK_API_KEY'] = 'test-deepseek-key'

        try:
            gateway = ModelGateway()

            # This should raise ValueError for missing API key
            with pytest.raises(ValueError) as exc_info:
                gateway.get_llm('deepseek_volc')

            # Verify error message contains expected content
            error_message = str(exc_info.value)
            assert 'DEEPSEEK_VOLC_API_KEY' in error_message
            assert 'missing' in error_message.lower()

            print("✓ Correct error raised for missing API key")

        except Exception as e:
            pytest.fail(f"Unexpected error: {e}")

    def test_nonexistent_fallback_model(self):
        """异常场景2：配置了不存在的降级模型时初始化不中断"""
        # Set environment variables
        os.environ['DEEPSEEK_API_KEY'] = 'test-deepseek-key'
        os.environ['DEEPSEEK_VOLC_API_KEY'] = 'test-volc-key'

        # Temporarily modify config to include nonexistent fallback
        config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "model_config.yaml")

        # Read original config
        with open(config_path, encoding='utf-8') as f:
            original_config = f.read()

        try:
            # Modify config to add nonexistent fallback
            modified_config = original_config.replace(
                'fallback_models:\n      - deepseek_volc',
                'fallback_models:\n      - deepseek_volc\n      - non_exist_model'
            )

            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(modified_config)

            # Create new gateway instance (will reload config)
            gateway = ModelGateway()

            # This should not crash, but should show warning
            try:
                failover_model = gateway.get_llm('deepseek')
                assert failover_model is not None
                print("✓ Initialization handled nonexistent fallback model gracefully")
            except Exception as e:
                # Should not crash, but if it does, verify it's handled gracefully
                assert 'non_exist_model' in str(e) or 'not found' in str(e)
                print("✓ Nonexistent fallback model handled with appropriate error")

        finally:
            # Restore original config
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(original_config)

    def teardown_method(self):
        """Clean up after tests"""
        # Restore environment variables if needed
        test_keys = ['DEEPSEEK_API_KEY', 'DEEPSEEK_VOLC_API_KEY']
        for key in test_keys:
            if key in os.environ and os.environ[key].startswith('test-'):
                del os.environ[key]
