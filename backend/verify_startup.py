"""
AgentRuntime 启动验证脚本
用于验证 AgentRuntime 初始化链路是否正常
"""
import asyncio
import os
import sys

from app.core.logging import get_logger

logger = get_logger(__name__)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

async def verify_startup():
    print("=" * 60)
    print("AgentRuntime 启动验证")
    print("=" * 60)

    try:
        print("\n[1/5] 导入 AgentRuntime...")
        from app.runtime.orchestrator import AgentRuntime
        print("OK - AgentRuntime 导入成功")

        print("\n[2/5] 创建 AgentRuntime 实例...")
        runtime = AgentRuntime()
        print("OK - AgentRuntime 实例创建成功")

        print("\n[3/5] 初始化 AgentRuntime（不真正调用 LLM 推理）...")
        await runtime.initialize()
        print("OK - AgentRuntime 初始化成功")

        print("\n[4/5] 验证组件...")
        assert runtime.llm is not None, "LLM 未初始化"
        assert runtime.mcp_tools is not None, "MCP 工具未加载"
        assert runtime.memory_manager is not None, "MemoryManager 未初始化"
        assert runtime.validator is not None, "DynamicValidator 未初始化"
        assert runtime.graph is not None, "StateGraph 未构建"
        assert runtime._initialized is True, "初始化标志未设置"
        print("OK - 所有组件已正确初始化")

        print("\n[5/5] 验证 Skill 注册表...")
        assert runtime.skill_registry is not None, "Skill 注册表未加载"
        print("OK - Skill 注册表正常，已加载技能")

        print("\n" + "=" * 60)
        print("AgentRuntime 启动验证完成！所有检查通过。")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\nERROR - 验证失败: {str(e)}")
        logger.error("startup_verification_failed", error=str(e))
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(verify_startup())
    sys.exit(0 if success else 1)
