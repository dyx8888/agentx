#!/usr/bin/env python3
"""
Setup test agents Amy and Ben for AgentX Stage 8 verification
"""

import json
import os
import sys

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import db


def setup_test_agents():
    """Create Amy, Ben, and CC agents in database"""

    # Create a test company first
    from app.database import Company
    company_data = Company(
        name="Test Company",
        brand_name="LisaBeauty",
        category="美妆",
        platforms_json=json.dumps(["小红书", "抖音", "微博"])
    )

    company_id = db.create_company(company_data)
    print(f"Created test company with ID: {company_id}")

    # Amy agent - Business specialist
    amy_tools = [
        "search_kols",
        "generate_outreach",
        "delegate_task",
        "get_current_time"
    ]

    # Amy agent - Business specialist
    from app.database import Agent
    amy_agent_data = Agent(
        company_id=company_id,
        name="Amy",
        description="专业的品牌商务数字员工，擅长达人营销和商务合作",
        tools_json=json.dumps(amy_tools)
    )

    amy_agent_id = db.create_agent(amy_agent_data)
    print(f"Created Amy agent with ID: {amy_agent_id}")

    # Ben agent - Data analysis specialist
    ben_tools = [
        "generate_performance_report",
        "generate_strategy_suggestion",
        "delegate_task",
        "get_current_time"
    ]

    ben_agent_data = Agent(
        company_id=company_id,
        name="Ben",
        description="专业的数据分析数字员工，擅长数据分析和策略建议",
        tools_json=json.dumps(ben_tools)
    )

    ben_agent_id = db.create_agent(ben_agent_data)
    print(f"Created Ben agent with ID: {ben_agent_id}")

    # CC agent - Content creation specialist
    cc_tools = [
        "generate_script",
        "delegate_task",
        "get_current_time"
    ]

    cc_agent_data = Agent(
        company_id=company_id,
        name="CC",
        description="专业的内容创作数字员工，擅长短视频脚本和创意文案撰写",
        tools_json=json.dumps(cc_tools)
    )

    cc_agent_id = db.create_agent(cc_agent_data)
    print(f"Created CC agent with ID: {cc_agent_id}")

    # BrandBD agent - Complete workflow specialist
    from app.agents.brand_bd import get_brand_bd_default_tools
    brand_bd_tools = get_brand_bd_default_tools()

    brand_bd_agent_data = Agent(
        company_id=company_id,
        name="BrandBD",
        description="品牌商务数字员工，擅长达人搜索、话术生成、物流监控和效果复盘",
        tools_json=json.dumps(brand_bd_tools)
    )

    brand_bd_agent_id = db.create_agent(brand_bd_agent_data)
    print(f"Created BrandBD agent with ID: {brand_bd_agent_id}")

    return company_id, amy_agent_id, ben_agent_id, cc_agent_id, brand_bd_agent_id

if __name__ == "__main__":
    print("Setting up test agents for AgentX Stage 8...")
    setup_test_agents()
    print("Test agents setup completed!")
