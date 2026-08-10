"""
Agent Workflow Tools
Additional tools for A2A workflow submission and management
"""
# 提供 A2A 工作流提交工具：让 Agent 通过结构化工作流（而非临时委托）协作，确保任务可追踪、可重试

# 导入 get_logger：记录工作流提交过程中的关键事件，便于在多 Agent 并发场景下排查问题
from app.core.logging import get_logger
# 导入 db 数据库访问对象：工作流和消息必须持久化存储，这样即使系统重启也不会丢失执行上下文
from app.database import db
# 导入 create_a2a_message：Agent 之间通过规范化消息通信，每条消息必须遵循 A2A 协议格式
from app.workflow.a2a_schema import create_a2a_message

# 使用 __name__ 创建模块级 logger：这样 log 输出会带上模块路径前缀，在多模块系统中能准确定位日志来源
logger = get_logger(__name__)

def submit_a2a_workflow(workflow_name: str, workflow_definition: str, company_id: int) -> str:
    # workflow_name：用于前端展示和日志标识，让运维人员知道提交了哪个工作流
    # workflow_definition：JSON 字符串描述工作流 DAG，定义了任务的拓扑结构和执行依赖关系
    # company_id：多租户隔离的关键字段，确保工作流只在当前公司数据上下文中执行，防止跨租户数据泄漏
    # 返回值是字符串而非复杂对象：方便 Agent 直接将返回消息嵌入回复文本中
    """
    Submit an A2A workflow for execution by the workflow engine.
    This allows agents to collaborate through predefined workflows instead of ad-hoc delegation.
    The workflow will be executed by the background workflow engine.
    
    Args:
        workflow_name: Name of the workflow to submit
        workflow_definition: JSON string defining the workflow DAG
        company_id: Company ID from agent runtime context
    
    Returns:
        Success message with workflow ID
    """
    # try/except 兜底：工作流提交涉及数据库写入和消息创建，任一环节都可能因网络波动或资源竞争失败，
    # 不能让异常向上冒泡到 Agent 主循环，否则会中断整个 Agent 服务
    try:
        # 先调用 create_a2a_message 生成消息对象：这是 "消息协议层"，用于 A2A 通信系统内部路由
        # 注意：这里生成的是 Python 对象，尚未持久化，但可以用于后续的日志记录或内容校验
        message = create_a2a_message(
            sender="System",  # 发送者固定为 System：表示工作流由系统调度触发，而非某个具体 Agent 的主动行为
            recipients=["WorkflowEngine"],  # 仅发送给 WorkflowEngine：工作流执行只有一个消费者，不需要广播
            task=f"Submit workflow '{workflow_name}' for execution",  # 任务描述含工作流名称：方便在消息面板中快速搜索
            task_type="workflow_submission",  # task_type 用于消息路由和过滤，引擎只处理类型匹配的消息
            company_id=company_id,  # company_id 在消息层面也做隔离：防止消息被错误路由到其他公司的 Agent
            payload={
                "workflow_name": workflow_name,  # payload 携带完整工作流名称和定义，引擎解析时不需要再查询数据库
                "definition": workflow_definition
            }
        )

        # 将消息写入数据库：这是 "持久化层"，即使后台引擎暂时不可用，消息也不会丢失
        # 引擎可以在恢复后从数据库拉取未处理的消息
        message_id = db.create_a2a_message(
            sender="System",
            recipients=["WorkflowEngine"],
            task=f"Submit workflow '{workflow_name}' for execution",
            task_type="workflow_submission",
            company_id=company_id,
            payload={
                "workflow_name": workflow_name,
                "definition": workflow_definition
            }
        )

        # 创建工作流实体：独立于消息表，用于追踪工作流的执行状态（待执行/执行中/已完成/失败）
        # 工作流实体是核心业务对象，消息只是通信载体，二者职责分离便于后续扩展
        workflow_id = db.create_workflow(company_id, workflow_name, workflow_definition)

        # 返回含 workflow_id 的成功消息：调用方可以用这个 ID 轮询工作流状态，实现异步执行 + 结果查询模式
        return f"Workflow '{workflow_name}' submitted. ID: {workflow_id}"

    except Exception as e:
        # 捕获所有异常并以字符串形式返回错误：Agent 期望拿到可读文本而非 traceback，确保对话流畅不中断
        return f"Error submitting workflow: {str(e)}"