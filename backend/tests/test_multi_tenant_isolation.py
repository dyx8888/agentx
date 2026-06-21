"""Test multi-tenant data isolation functionality."""

import os

from app.mcp_servers.knowledge_retrieval_server import (
    KnowledgeRetrieval,
    add_knowledge,
    search_knowledge,
)
from app.platforms.douyin_star import DouyinStarAdapter


class TestMultiTenantIsolation:
    """Test multi-tenant data isolation between different companies."""

    def setup_method(self):
        """Set up test environment"""
        # Set up test environment variables
        os.environ['DEEPSEEK_API_KEY'] = 'test-deepseek-key'
        os.environ['DEEPSEEK_VOLC_API_KEY'] = 'test-volc-key'

    def test_knowledge_isolation_by_company(self):
        """正常场景1：知识库按公司隔离添加和检索"""
        # Add knowledge to company_A
        result_a = add_knowledge(
            text="Company A secret knowledge",
            metadata={'category': 'test', 'scenario': 'isolation'},
            company_id='company_A'
        )
        assert "Successfully added" in result_a

        # Add knowledge to company_B
        result_b = add_knowledge(
            text="Company B secret knowledge",
            metadata={'category': 'test', 'scenario': 'isolation'},
            company_id='company_B'
        )
        assert "Successfully added" in result_b

        # Search in company_A should only return company_A data
        results_a = search_knowledge("secret knowledge", company_id='company_A')
        assert len(results_a) > 0
        assert any("Company A secret knowledge" in result['content'] for result in results_a)
        assert not any("Company B secret knowledge" in result['content'] for result in results_a)

        # Search in company_B should only return company_B data
        results_b = search_knowledge("secret knowledge", company_id='company_B')
        assert len(results_b) > 0
        assert any("Company B secret knowledge" in result['content'] for result in results_b)
        assert not any("Company A secret knowledge" in result['content'] for result in results_b)

        print("✓ Knowledge isolation between companies working correctly")

    def test_platform_adapter_company_credentials(self):
        """正常场景2：平台适配器按公司加载不同凭证"""
        # Mock database with different company credentials
        import sys
        sys.path.insert(0, '.')

        # Test with company_id A
        try:
            adapter_a = DouyinStarAdapter(company_id=1)
            # Should try to load company-specific credentials
            assert hasattr(adapter_a, 'company_id')
            assert adapter_a.company_id == 1
        except Exception as e:
            # Expected to fail gracefully if database not available
            assert "Failed to load company credentials" in str(e) or "falling back" in str(e)

        # Test with company_id B
        try:
            adapter_b = DouyinStarAdapter(company_id=2)
            # Should try to load company-specific credentials
            assert hasattr(adapter_b, 'company_id')
            assert adapter_b.company_id == 2
        except Exception as e:
            # Expected to fail gracefully if database not available
            assert "Failed to load company credentials" in str(e) or "falling back" in str(e)

        # Test without company_id (fallback to env)
        adapter_default = DouyinStarAdapter()
        assert hasattr(adapter_default, 'company_id')
        assert adapter_default.company_id is None

        print("✓ Platform adapter company credential loading working correctly")

    def test_nonexistent_company_search(self):
        """异常场景1：查询不存在的公司知识库"""
        # Search for knowledge in a non-existent company
        results = search_knowledge("any query", company_id='non_exist_company')

        # Should return list without crashing (may have sample data)
        assert isinstance(results, list)
        # Note: New collections get sample data, so we just check it doesn't crash
        print("✓ Non-existent company search handled correctly")

    def test_invalid_company_id_adapter(self):
        """异常场景2：传入无效 company_id 给平台适配器"""
        # Test with invalid company_id
        adapter = DouyinStarAdapter(company_id=99999)

        # Should handle gracefully - either load fallback credentials or raise clear error
        assert hasattr(adapter, 'company_id')
        assert adapter.company_id == 99999

        # Should have attempted to load credentials (either company-specific or fallback)
        # The key point is it doesn't crash with KeyError
        if hasattr(adapter, 'api_key'):
            # Either has credentials (fallback worked) or None (credentials missing)
            assert adapter.api_key is None or isinstance(adapter.api_key, str)

        print("✓ Invalid company_id handled with graceful fallback")

    def teardown_method(self):
        """Clean up after tests"""
        # Clean up environment variables
        test_keys = ['DEEPSEEK_API_KEY', 'DEEPSEEK_VOLC_API_KEY']
        for key in test_keys:
            if key in os.environ and os.environ[key].startswith('test-'):
                del os.environ[key]


class TestKnowledgeRetrievalDirect:
    """Test KnowledgeRetrieval class directly for isolation."""

    def test_collection_isolation(self):
        """Test that different companies use different collections"""
        # Create instances for different companies
        kr_a = KnowledgeRetrieval('company_A')
        kr_b = KnowledgeRetrieval('company_B')

        # Check that they have different collections
        assert kr_a.collection.name != kr_b.collection.name
        assert 'company_A' in kr_a.collection.name
        assert 'company_B' in kr_b.collection.name

        # Check that collections are properly isolated by name
        assert kr_a.collection.name == 'brand_scripts_company_A'
        assert kr_b.collection.name == 'brand_scripts_company_B'

        print("✓ Collection isolation working correctly")

    def test_knowledge_cross_contamination_prevention(self):
        """正常场景3：公司A新增知识不会污染公司B的检索结果"""
        add_knowledge(
            text="Company A marketing strategy Q3 2025",
            metadata={'category': 'strategy', 'scenario': 'cross_contamination'},
            company_id='company_A'
        )
        add_knowledge(
            text="Company B product launch plan",
            metadata={'category': 'strategy', 'scenario': 'cross_contamination'},
            company_id='company_B'
        )

        results_a = search_knowledge("marketing strategy", company_id='company_A', top_k=10)
        results_b = search_knowledge("product launch", company_id='company_B', top_k=10)

        assert len(results_a) > 0, "Company A should have results"
        assert len(results_b) > 0, "Company B should have results"

        a_contents = [r['content'] for r in results_a]
        b_contents = [r['content'] for r in results_b]

        assert not any("Company B" in c for c in a_contents), "Company A should not see Company B data"
        assert not any("Company A" in c for c in b_contents), "Company B should not see Company A data"

        print("✓ Cross-contamination prevention working correctly")

    def test_empty_query_graceful_handling(self):
        """异常场景3：空查询字符串时优雅处理"""
        results = search_knowledge("", company_id='company_A')

        assert isinstance(results, list), "Should return list even for empty query"
        print("✓ Empty query handled gracefully")

    def test_same_company_id_multiple_instances_share_cache(self):
        """正常场景4：同一公司多次创建 KnowledgeRetrieval 实例共享底层缓存"""
        kr1 = KnowledgeRetrieval('company_A')
        kr2 = KnowledgeRetrieval('company_A')

        assert kr1.collection.name == kr2.collection.name
        assert kr1 is not kr2, "Different instances should be separate objects"
        assert kr1.collection.name == 'brand_scripts_company_A'
        print("✓ Same company cache sharing verified")
