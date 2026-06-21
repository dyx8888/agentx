# ==========================================
# 任务管理 API
# ==========================================
# 这个文件负责管理异步任务
# 异步任务：需要长时间执行的任务，用户不用一直等待结果
# 比如：数据分析、批量处理、生成报告等
# 主要功能：
# 1. 创建任务（放入队列）
# 2. 查询任务状态
# 3. 获取任务列表
# 4. 取消任务
# 5. 人工确认任务步骤
"""
Task Management API
Provides endpoints for asynchronous task creation and management
"""

# FastAPI 核心工具
from fastapi import APIRouter, Depends, HTTPException
# Pydantic：定义数据格式
from pydantic import BaseModel, field_validator

# 认证依赖：确保只有登录用户能创建/查看任务
from app.auth import get_current_active_user
# 数据库相关：User 模型和数据库操作对象
from app.database import User, db
# 输入过滤：防止任务描述中的 SQL 注入和 XSS 攻击
from app.middleware.input_filter import InputFilter

# 创建路由对象
router = APIRouter(tags=["tasks"])

# ==========================================
# 数据格式定义
# ==========================================

# 创建任务的请求格式
class CreateTaskRequest(BaseModel):
    source_agent_id: int | None = None  # 可选：发起任务的 Agent ID（None 表示用户直接发起）
    target_agent_name: str              # 必填：目标 Agent 名称（任务要交给哪个 Agent 执行）
    task_description: str               # 必填：任务描述（告诉 Agent 要做什么）

    # 任务描述过滤：防止恶意输入
    @field_validator('task_description')
    @classmethod
    def filter_task_description(cls, v: str) -> str:
        return InputFilter.validate_message(v)

# 创建任务的响应格式
class CreateTaskResponse(BaseModel):
    task_id: int   # 任务 ID（用于后续查询状态）
    status: str    # 任务状态（新创建的任务默认 "pending"）

# 任务详情的响应格式
class TaskResponse(BaseModel):
    id: int                      # 任务 ID
    company_id: int              # 所属公司 ID（租户隔离）
    source_agent_id: int | None  # 发起任务的 Agent ID（可能为 None）
    target_agent_name: str       # 目标 Agent 名称
    task_description: str        # 原始任务描述
    status: str                  # 任务状态：pending / processing / completed / failed / cancelled
    result: str | None           # 任务执行结果（进行中或失败时可能为 None）
    created_at: str              # 创建时间
    completed_at: str | None     # 完成时间（未完成时为 None）

# 任务列表的响应格式
class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]  # 任务列表
    total: int                 # 总数（用于前端分页）

# 任务执行步骤的格式
class TaskStep(BaseModel):
    step_id: int               # 步骤序号
    name: str                  # 步骤名称
    status: str                # 步骤状态：pending / processing / confirm_required / completed / rejected
    result: str | None = None  # 步骤结果（需要确认时可能为空）

# 任务步骤列表的响应格式
class TaskStepsResponse(BaseModel):
    task_id: int               # 所属任务 ID
    steps: list[TaskStep]      # 步骤列表

# 人工确认的请求格式
class TaskConfirmationRequest(BaseModel):
    step_id: int               # 需要确认的步骤 ID
    action: str                # 确认动作：approve（批准）/ reject（拒绝）/ modify（修改）
    modified_content: str | None = None  # modify 时的修改内容

# ==========================================
# API 接口：创建任务
# ==========================================
# POST /api/tasks
# 创建一个异步任务（放入队列等待处理）
@router.post("/", response_model=CreateTaskResponse)
async def create_task(
    request: CreateTaskRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Create an asynchronous task
    Returns task ID for tracking
    """
    try:
        # 在数据库中创建任务记录
        task_id = db.create_task(
            company_id=current_user.company_id,  # 自动绑定用户公司（租户隔离）
            source_agent_id=request.source_agent_id,
            target_agent_name=request.target_agent_name,
            task_description=request.task_description
        )

        # 返回任务 ID（用于后续查询状态）
        return CreateTaskResponse(
            task_id=task_id,
            status="pending"  # 新创建的任务默认状态为 pending（等待处理）
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating task: {str(e)}")

# ==========================================
# API 接口：查询单个任务
# ==========================================
# GET /api/tasks/{task_id}
# 查询任务的详细信息和当前状态
@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    current_user: User = Depends(get_current_active_user)
):
    """
    Get task status and details
    Ensures task belongs to current user's company
    """
    try:
        # 查询任务详情
        task = db.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 验证权限：用户只能查看自己公司的任务（租户隔离）
        if task['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 返回任务详情
        return TaskResponse(
            id=task['id'],
            company_id=task['company_id'],
            source_agent_id=task['source_agent_id'],
            target_agent_name=task['target_agent_name'],
            task_description=task['task_description'],
            status=task['status'],
            result=task['result'],
            created_at=task['created_at'],
            completed_at=task['completed_at']
        )

    except HTTPException:
        raise  # 重新抛出 HTTPException，保持原有状态码
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting task: {str(e)}")

# ==========================================
# API 接口：获取任务列表
# ==========================================
# GET /api/tasks
# 获取当前公司的所有任务（支持分页）
@router.get("/", response_model=TaskListResponse)
async def get_tasks(
    limit: int = 50,  # 默认返回 50 条，避免一次返回过多数据
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all tasks for current user's company
    Supports pagination with limit parameter
    """
    try:
        # 查询公司的任务列表
        tasks = db.get_company_tasks(current_user.company_id, limit)

        # 转换为响应格式
        task_responses = []
        for task in tasks:
            task_responses.append(TaskResponse(
                id=task['id'],
                company_id=task['company_id'],
                source_agent_id=task['source_agent_id'],
                target_agent_name=task['target_agent_name'],
                task_description=task['task_description'],
                status=task['status'],
                result=task['result'],
                created_at=task['created_at'],
                completed_at=task['completed_at']
            ))

        # 返回任务列表和总数
        return TaskListResponse(
            tasks=task_responses,
            total=len(task_responses)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting tasks: {str(e)}")

# ==========================================
# API 接口：获取待处理任务
# ==========================================
# GET /api/tasks/pending
# 获取当前公司所有待处理的任务（用于监控任务队列）
@router.get("/pending", response_model=TaskListResponse)
async def get_pending_tasks(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get all pending tasks for current user's company
    Useful for monitoring task queue
    """
    try:
        # 查询所有待处理任务
        all_pending = db.get_pending_tasks()

        # 过滤出当前公司的任务
        company_pending = [
            task for task in all_pending
            if task['company_id'] == current_user.company_id
        ]

        # 转换为响应格式
        task_responses = []
        for task in company_pending:
            task_responses.append(TaskResponse(
                id=task['id'],
                company_id=task['company_id'],
                source_agent_id=task['source_agent_id'],
                target_agent_name=task['target_agent_name'],
                task_description=task['task_description'],
                status="pending",
                result=None,
                created_at="",
                completed_at=None
            ))

        return TaskListResponse(
            tasks=task_responses,
            total=len(task_responses)
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pending tasks: {str(e)}")

# ==========================================
# API 接口：取消任务
# ==========================================
# DELETE /api/tasks/{task_id}
# 取消一个待处理的任务（只能取消 pending 状态的任务）
@router.delete("/{task_id}")
async def cancel_task(
    task_id: int,
    current_user: User = Depends(get_current_active_user)
):
    """
    Cancel a pending task
    Only allows cancellation of pending tasks
    """
    try:
        # 查询任务详情
        task = db.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 验证权限：用户只能取消自己公司的任务
        if task['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 只能取消 pending 状态的任务（防止误操作进行中的任务）
        if task['status'] != 'pending':
            raise HTTPException(status_code=400, detail="Cannot cancel task that is not pending")

        # 更新任务状态为 cancelled
        db.update_task_status(task_id, 'cancelled')

        return {"message": "Task cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error cancelling task: {str(e)}")

# ==========================================
# API 接口：获取任务步骤
# ==========================================
# GET /api/tasks/{task_id}/steps
# 获取任务的详细执行步骤（需要人工确认的步骤）
@router.get("/{task_id}/steps", response_model=TaskStepsResponse)
async def get_task_steps(
    task_id: int,
    current_user: User = Depends(get_current_active_user)
):
    """
    Get detailed execution steps for a task
    Only accessible to users from the same company
    """
    try:
        # 查询任务详情
        task = db.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 验证权限：用户只能查看自己公司的任务
        if task['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 解析任务步骤（任务结果中可能包含步骤信息）
        steps = []
        if task['result']:
            try:
                import json
                steps_data = json.loads(task['result'])
                if isinstance(steps_data, dict) and 'steps' in steps_data:
                    steps = steps_data['steps']  # 提取 steps 字段
                elif isinstance(steps_data, list):
                    steps = steps_data  # 直接是列表格式
            except (json.JSONDecodeError, KeyError):
                steps = []  # JSON 解析失败时返回空列表

        return TaskStepsResponse(
            task_id=task_id,
            steps=steps
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting task steps: {str(e)}")

# ==========================================
# API 接口：确认任务步骤
# ==========================================
# POST /api/tasks/{task_id}/confirm
# 人工审核任务步骤（批准/拒绝/修改）
# 当 Agent 执行到需要人工确认的步骤时，会暂停等待用户确认
@router.post("/{task_id}/confirm")
async def confirm_task_step(
    task_id: int,
    request: TaskConfirmationRequest,
    current_user: User = Depends(get_current_active_user)
):
    """
    Confirm/modify/reject a task step that requires human confirmation
    Only accessible to users from the same company
    """
    try:
        # 第一步：查询任务详情
        task = db.get_task(task_id)

        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # 第二步：验证权限（租户隔离）
        if task['company_id'] != current_user.company_id:
            raise HTTPException(status_code=403, detail="Access denied")

        # 第三步：解析任务步骤（从任务结果中提取）
        steps = []
        if task['result']:
            try:
                import json
                steps_data = json.loads(task['result'])
                if isinstance(steps_data, dict) and 'steps' in steps_data:
                    steps = steps_data['steps']
                elif isinstance(steps_data, list):
                    steps = steps_data
            except (json.JSONDecodeError, KeyError):
                steps = []

        # 第四步：找到目标步骤
        target_step = None
        for step in steps:
            if step.get('step_id') == request.step_id:
                target_step = step
                break

        if not target_step:
            raise HTTPException(status_code=404, detail="Step not found")

        # 第五步：验证步骤状态（只能确认 confirm_required 状态的步骤）
        if target_step.get('status') != 'confirm_required':
            raise HTTPException(status_code=400, detail="Step is not in confirm_required status")

        # 第六步：处理确认动作
        if request.action == 'approve':
            # 批准：步骤完成，继续执行后续步骤
            target_step['status'] = 'completed'
            target_step['result'] = 'Approved by user'

        elif request.action == 'reject':
            # 拒绝：步骤失败，整个任务也标记为失败
            target_step['status'] = 'rejected'
            target_step['result'] = 'Rejected by user'
            db.update_task_status(task_id, 'failed', json.dumps({'steps': steps}))
            return {"message": "Step rejected, task marked as failed"}

        elif request.action == 'modify':
            # 修改：用户修改步骤内容后继续执行
            if not request.modified_content:
                raise HTTPException(status_code=400, detail="modified_content is required for modify action")
            target_step['status'] = 'completed'
            target_step['result'] = request.modified_content

        else:
            raise HTTPException(status_code=400, detail="Invalid action. Must be approve, reject, or modify")

        # 第七步：保存更新后的步骤
        updated_result = json.dumps({'steps': steps})

        # 第八步：检查是否所有步骤都已完成
        all_completed = all(step.get('status') in ['completed', 'rejected'] for step in steps)
        if all_completed:
            # 全部完成：任务标记为完成
            db.update_task_status(task_id, 'completed', updated_result)
        else:
            # 还有步骤：任务继续处理
            db.update_task_status(task_id, 'processing', updated_result)

        return {"message": f"Step {request.action}d successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error confirming task step: {str(e)}")
