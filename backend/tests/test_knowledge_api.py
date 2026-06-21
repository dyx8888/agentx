"""Test Knowledge Management API endpoints."""

from fastapi.testclient import TestClient

from app.main import app


class TestKnowledgeAPI:
    """Test knowledge upload and search API endpoints."""

    def setup_method(self):
        """Set up test client"""
        self.client = TestClient(app)
        self.test_company_id = "test_company_4"

    def test_upload_and_search_knowledge(self):
        """正常场景1：上传知识并成功检索"""
        # Upload knowledge
        upload_data = {
            "content": "我们的产品主打纯天然成分，不含任何化学添加剂，适合敏感肌肤使用。",
            "category": "product",
            "scenario": "product_intro",
            "company_id": self.test_company_id
        }

        upload_response = self.client.post("/knowledge/upload", json=upload_data)
        assert upload_response.status_code == 200

        upload_result = upload_response.json()
        assert upload_result["status"] == "success"
        assert "doc_id" in upload_result
        doc_id = upload_result["doc_id"]

        # Search for the uploaded knowledge
        search_response = self.client.get(
            "/knowledge/search",
            params={
                "query": "纯天然",
                "n_results": 5,
                "company_id": self.test_company_id
            }
        )
        assert search_response.status_code == 200

        search_results = search_response.json()
        assert isinstance(search_results, list)
        assert len(search_results) > 0

        # Verify the uploaded content is in the search results
        found_content = False
        for result in search_results:
            if "纯天然成分" in result["content"]:
                found_content = True
                assert result["metadata"]["category"] == "product"
                assert result["metadata"]["scenario"] == "product_intro"
                assert result["metadata"]["source"] == "api_upload"
                break

        assert found_content, "Uploaded knowledge not found in search results"
        print("✓ Upload and search knowledge working correctly")

    def test_upload_with_category_and_scenario(self):
        """正常场景2：上传带分类和场景的知识"""
        # Upload knowledge with specific category and scenario
        upload_data = {
            "content": "这款护肤品采用玻尿酸和维生素C配方，深层保湿同时提亮肤色。",
            "category": "beauty",
            "scenario": "product_intro",
            "company_id": self.test_company_id
        }

        upload_response = self.client.post("/knowledge/upload", json=upload_data)
        assert upload_response.status_code == 200

        # Search and verify metadata
        search_response = self.client.get(
            "/knowledge/search",
            params={
                "query": "玻尿酸",
                "n_results": 3,
                "company_id": self.test_company_id
            }
        )
        assert search_response.status_code == 200

        search_results = search_response.json()
        assert len(search_results) > 0

        # Find the uploaded content and verify metadata
        found = False
        for result in search_results:
            if "玻尿酸" in result["content"]:
                assert result["metadata"]["category"] == "beauty"
                assert result["metadata"]["scenario"] == "product_intro"
                assert result["metadata"]["source"] == "api_upload"
                found = True
                break

        assert found, "Knowledge with specific category/scenario not found"
        print("✓ Upload with category and scenario working correctly")

    def test_upload_empty_content(self):
        """异常场景1：上传空内容"""
        # Test with empty content
        upload_data = {
            "content": "",
            "category": "test",
            "scenario": "test",
            "company_id": self.test_company_id
        }

        response = self.client.post("/knowledge/upload", json=upload_data)
        assert response.status_code == 422

        error_result = response.json()
        assert "detail" in error_result

        # Test with whitespace-only content
        upload_data["content"] = "   "
        response = self.client.post("/knowledge/upload", json=upload_data)
        assert response.status_code == 400

        print("✓ Empty content validation working correctly")

    def test_search_missing_company_id(self):
        """异常场景2：检索时缺少必填的 company_id"""
        # Test search without company_id
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "test",
                "n_results": 3
                # Missing company_id
            }
        )
        assert response.status_code == 422

        error_result = response.json()
        assert "detail" in error_result

        # Test search with empty company_id
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "test",
                "n_results": 3,
                "company_id": ""
            }
        )
        # FastAPI should handle empty string as valid but search should handle it
        assert response.status_code in [200, 422]

        print("✓ Missing company_id validation working correctly")

    def test_upload_content_length_limit(self):
        """测试内容长度限制"""
        # Test with content exceeding 5000 characters
        long_content = "a" * 5001
        upload_data = {
            "content": long_content,
            "category": "test",
            "scenario": "test",
            "company_id": self.test_company_id
        }

        response = self.client.post("/knowledge/upload", json=upload_data)
        assert response.status_code == 422

        error_result = response.json()
        assert "detail" in error_result

        # Test with exactly 5000 characters (should work)
        valid_content = "a" * 5000
        upload_data["content"] = valid_content

        response = self.client.post("/knowledge/upload", json=upload_data)
        assert response.status_code == 200

        print("✓ Content length validation working correctly")

    def test_search_query_validation(self):
        """测试搜索查询验证"""
        # Test with empty query
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "",
                "n_results": 3,
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 400

        error_result = response.json()
        # Check for error message in either detail or message field
        error_message = error_result.get("detail", error_result.get("message", ""))
        assert "Query cannot be empty" in error_message

        # Test with whitespace-only query
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "   ",
                "n_results": 3,
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 400

        print("✓ Search query validation working correctly")

    def test_n_results_validation(self):
        """测试结果数量验证"""
        # Test with n_results = 0 (should fail)
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "test",
                "n_results": 0,
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 422

        # Test with n_results > 20 (should fail)
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "test",
                "n_results": 21,
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 422

        # Test with valid n_results range
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "test",
                "n_results": 15,
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 200

        print("✓ n_results validation working correctly")

    def test_default_values(self):
        """测试默认值"""
        # Upload without category and scenario (should use defaults)
        upload_data = {
            "content": "测试默认值的内容",
            "company_id": self.test_company_id
        }

        response = self.client.post("/knowledge/upload", json=upload_data)
        assert response.status_code == 200

        # Search and verify default values
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "默认值",
                "company_id": self.test_company_id
            }
        )
        assert response.status_code == 200

        results = response.json()
        found = False
        for result in results:
            if "默认值" in result["content"]:
                assert result["metadata"]["category"] == "general"
                assert result["metadata"]["scenario"] == "general"
                found = True
                break

        assert found, "Default values not applied correctly"

        # Test default n_results in search
        response = self.client.get(
            "/knowledge/search",
            params={
                "query": "默认值",
                "company_id": self.test_company_id
                # n_results not specified, should default to 3
            }
        )
        assert response.status_code == 200

        print("✓ Default values working correctly")
