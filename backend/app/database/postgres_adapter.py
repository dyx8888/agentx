"""
PostgreSQL Adapter for Database Migration
Provides PostgreSQL support while maintaining backward compatibility with DatabaseManager interface
"""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.logging import get_logger

from .core import get_engine
from .models import Agent, Company, EvolutionLog, Feedback, Task, User

logger = get_logger(__name__)


class PostgresAdapter:
    """PostgreSQL adapter that implements the same interface as DatabaseManager"""

    def __init__(self):
        self.engine = get_engine()
        if self.engine is None:
            raise RuntimeError(
                "PostgreSQL not configured. Please set DATABASE_URL environment variable."
            )

        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    def health_check(self) -> dict:
        """Check database connectivity and return health status"""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return {"status": "healthy"}
        except Exception as e:
            logger.error("postgres_health_check_failed", error=str(e))
            return {"status": "unhealthy", "error": str(e)}

    def get_connection(self):
        """Get database connection for backward compatibility"""
        # Return a context manager that provides execute method
        return ConnectionContext(self.engine)

    def get_session(self):
        """Get SQLAlchemy session"""
        return self.SessionLocal()

    def create_user(self, user: User) -> int:
        """Create a new user"""
        try:
            with self.get_session() as session:
                orm_user = self._to_orm_user(user)
                session.add(orm_user)
                session.commit()
                return orm_user.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create user: {e}")

    def _to_orm_user(self, user):
        if isinstance(user, User):
            return user
        orm_user = User(
            username=user.username,
            password_hash=user.password_hash,
            company_id=user.company_id,
            is_admin=getattr(user, "is_admin", False),
            disabled=getattr(user, "disabled", False),
        )
        return orm_user

    def get_user(self, user_id: int) -> User | None:
        """Get user by ID"""
        try:
            with self.get_session() as session:
                return session.query(User).filter(User.id == user_id).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_user", resource_id=user_id, error=str(e))
            return None

    def get_user_by_id(self, user_id: int):
        """Get user by ID (alias for get_user)"""
        return self.get_user(user_id)

    def get_user_by_username(self, username: str) -> User | None:
        """Get user by username"""
        try:
            with self.get_session() as session:
                return session.query(User).filter(User.username == username).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_user_by_username", username=username, error=str(e))
            return None

    def get_users_by_company(self, company_id: int) -> list[User]:
        """Get users by company"""
        try:
            with self.get_session() as session:
                return session.query(User).filter(User.company_id == company_id).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_users_by_company", resource_id=company_id, error=str(e))
            return []

    def create_company(self, company: Company) -> int:
        """Create a new company"""
        try:
            with self.get_session() as session:
                session.add(company)
                session.commit()
                return company.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create company: {e}")

    def get_company(self, company_id: int) -> Company | None:
        """Get company by ID"""
        try:
            with self.get_session() as session:
                return session.query(Company).filter(Company.id == company_id).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_company", resource_id=company_id, error=str(e))
            return None

    def get_companies_by_user(self, user_id: int) -> list[Company]:
        """Get companies by user"""
        try:
            with self.get_session() as session:
                # 修正：原先错误地用 Company.id == user_id 比较，实际应通过 User.company_id 关联
                # User.company_id 是指向 companies.id 的外键，需 join 后按 User.id 过滤
                return (
                    session.query(Company)
                    .join(User, User.company_id == Company.id)
                    .filter(User.id == user_id)
                    .all()
                )
        except SQLAlchemyError as e:
            logger.error("postgres_get_companies_by_user", resource_id=user_id, error=str(e))
            return []

    def get_all_companies(self) -> list[Company]:
        """Get all companies"""
        try:
            with self.get_session() as session:
                return session.query(Company).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_all_companies", error=str(e))
            return []

    def get_active_company_ids(self) -> list[int]:
        """获取有 Agent 的活跃租户 company_id 列表。

        用于定时任务（如睡眠巩固）遍历需要处理的租户。
        以 agents 表中出现的 distinct company_id 为"活跃"判据——
        没有 Agent 的租户无需做进化/巩固，避免对空租户无意义运算。
        """
        try:
            with self.get_session() as session:
                rows = session.query(Agent.company_id).distinct().all()
                return [r[0] for r in rows if r[0] is not None]
        except SQLAlchemyError as e:
            logger.error("postgres_get_active_company_ids", error=str(e))
            return []

    def update_company(self, company_id: int, company: Company) -> bool:
        """Update company information"""
        try:
            with self.get_session() as session:
                existing = session.query(Company).filter(Company.id == company_id).first()
                if not existing:
                    return False

                # Update fields
                for key, value in company.dict(exclude_unset=True).items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)

                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_company", resource_id=company_id, error=str(e))
            return False

    def delete_company(self, company_id: int) -> bool:
        """Delete a company"""
        try:
            with self.get_session() as session:
                company = session.query(Company).filter(Company.id == company_id).first()
                if company:
                    session.delete(company)
                    session.commit()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error("postgres_delete_company", resource_id=company_id, error=str(e))
            return False

    def create_agent(self, agent: Agent) -> int:
        """Create a new agent"""
        try:
            with self.get_session() as session:
                session.add(agent)
                session.commit()
                return agent.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create agent: {e}")

    def get_agent(self, agent_id: int) -> Agent | None:
        """Get agent by ID"""
        try:
            with self.get_session() as session:
                return session.query(Agent).filter(Agent.id == agent_id).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_agent", resource_id=agent_id, error=str(e))
            return None

    def get_agent_by_name(self, name: str) -> Agent | None:
        """Get agent by name"""
        try:
            with self.get_session() as session:
                return session.query(Agent).filter(Agent.name == name).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_agent_by_name", resource_id=name, error=str(e))
            return None

    def get_agents_by_company(self, company_id: int) -> list[Agent]:
        """Get agents by company"""
        try:
            with self.get_session() as session:
                return session.query(Agent).filter(Agent.company_id == company_id).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_agent", resource_id=company_id, error=str(e))
            return []

    def get_all_agents(self) -> list[Agent]:
        """Get all agents"""
        try:
            with self.get_session() as session:
                return session.query(Agent).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_all_agents", error=str(e))
            return []

    def count_agents_by_company(self, company_id: int) -> int:
        """Count agents for a company"""
        try:
            with self.get_session() as session:
                return session.query(Agent).filter(Agent.company_id == company_id).count()
        except SQLAlchemyError:
            return 0

    def count_users_by_company(self, company_id: int) -> int:
        """Count users for a company"""
        try:
            with self.get_session() as session:
                return session.query(User).filter(User.company_id == company_id).count()
        except SQLAlchemyError:
            return 0

    def get_all_users(self) -> list[User]:
        """Get all users"""
        try:
            with self.get_session() as session:
                return session.query(User).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_all_users", error=str(e))
            return []

    def update_agent(self, agent_id: int, agent: Agent) -> bool:
        """Update agent information"""
        try:
            with self.get_session() as session:
                existing = session.query(Agent).filter(Agent.id == agent_id).first()
                if not existing:
                    return False

                # Update fields
                for key, value in agent.dict(exclude_unset=True).items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)

                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_agent", resource_id=agent_id, error=str(e))
            return False

    def delete_agent(self, agent_id: int) -> bool:
        """Delete an agent"""
        try:
            with self.get_session() as session:
                agent = session.query(Agent).filter(Agent.id == agent_id).first()
                if agent:
                    session.delete(agent)
                    session.commit()
                    return True
                return False
        except SQLAlchemyError as e:
            logger.error("postgres_delete_agent", resource_id=agent_id, error=str(e))
            return False

    def create_task(
        self,
        company_id: int,
        source_agent_id: int = None,
        target_agent_name: str = None,
        task_description: str = None,
    ) -> int:
        """Create a new task"""
        try:
            from .models import Task

            task = Task(
                company_id=company_id,
                source_agent_id=source_agent_id,
                target_agent_name=target_agent_name,
                task_description=task_description,
                status="pending",
            )
            with self.get_session() as session:
                session.add(task)
                session.commit()
                return task.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create task: {e}")

    def update_task_status(self, task_id: int, status: str, result: str = None):
        """Update task status and result"""
        try:
            with self.get_session() as session:
                task = session.query(Task).filter(Task.id == task_id).first()
                if not task:
                    return False

                task.status = status
                if result is not None:
                    task.result = result
                task.completed_at = datetime.utcnow() if status in ["completed", "failed"] else None

                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_task", resource_id=task_id, error=str(e))
            return False

    def get_task(self, task_id: int) -> dict | None:
        """Get task details by ID"""
        try:
            with self.get_session() as session:
                task = session.query(Task).filter(Task.id == task_id).first()
                if not task:
                    return None

                return {
                    "id": task.id,
                    "company_id": task.company_id,
                    "source_agent_id": task.source_agent_id,
                    "target_agent_name": task.target_agent_name,
                    "task_description": task.task_description,
                    "status": task.status,
                    "result": task.result,
                    "created_at": task.created_at.isoformat() if task.created_at else None,
                    "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                }
        except SQLAlchemyError as e:
            logger.error("postgres_get_task", resource_id=task_id, error=str(e))
            return None

    def get_pending_tasks(self) -> list[dict]:
        """Get all pending tasks"""
        try:
            with self.get_session() as session:
                tasks = session.query(Task).filter(Task.status == "pending").all()
                return [
                    {
                        "id": task.id,
                        "company_id": task.company_id,
                        "source_agent_id": task.source_agent_id,
                        "target_agent_name": task.target_agent_name,
                        "task_description": task.task_description,
                    }
                    for task in tasks
                ]
        except SQLAlchemyError as e:
            logger.error("postgres_get_pending_tasks", error=str(e))
            return []

    def get_company_tasks(self, company_id: int, limit: int = 50) -> list[dict]:
        """Get tasks for a specific company"""
        try:
            with self.get_session() as session:
                tasks = (
                    session.query(Task)
                    .filter(Task.company_id == company_id)
                    .order_by(Task.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return [
                    {
                        "id": task.id,
                        "company_id": task.company_id,
                        "source_agent_id": task.source_agent_id,
                        "target_agent_name": task.target_agent_name,
                        "task_description": task.task_description,
                        "status": task.status,
                        "result": task.result,
                        "created_at": task.created_at.isoformat() if task.created_at else None,
                        "completed_at": task.completed_at.isoformat()
                        if task.completed_at
                        else None,
                    }
                    for task in tasks
                ]
        except SQLAlchemyError as e:
            logger.error("postgres_get_company", resource_id=company_id, error=str(e))
            return []

    def create_feedback(self, feedback: Feedback) -> int:
        """Create a new feedback entry"""
        try:
            with self.get_session() as session:
                session.add(feedback)
                session.commit()
                return feedback.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create feedback: {e}")

    def get_feedback_by_agent(self, agent_id: int, limit: int = 100) -> list[Feedback]:
        """Get feedback for an agent"""
        try:
            with self.get_session() as session:
                feedbacks = (
                    session.query(Feedback)
                    .filter(Feedback.agent_id == agent_id)
                    .order_by(Feedback.created_at.desc())
                    .limit(limit)
                    .all()
                )
                return feedbacks
        except SQLAlchemyError as e:
            logger.error("postgres_get_feedback", resource_id=agent_id, error=str(e))
            return []

    def create_evolution_log(
        self,
        agent_id: int,
        suggestion_text: str,
        tool_name: str = None,
        training_data_path: str = None,
    ) -> int:
        """Create evolution log entry"""
        try:
            from .models import EvolutionLog

            evolution_log = EvolutionLog(
                agent_id=agent_id,
                tool_name=tool_name,
                suggestion_text=suggestion_text,
                training_data_path=training_data_path,
                applied=False,
            )
            with self.get_session() as session:
                session.add(evolution_log)
                session.commit()
                return evolution_log.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create evolution log: {e}")

    def create_evolution_review(
        self,
        agent_id: int,
        tool_name: str = None,
        suggestion_text: str = None,
        knowledge_entries: str = None,
        prompt_changes: str = None,
    ) -> int:
        """Create evolution review entry (pending human approval)"""
        try:
            from .models import EvolutionReview

            review = EvolutionReview(
                agent_id=agent_id,
                tool_name=tool_name,
                suggestion_text=suggestion_text,
                knowledge_entries=knowledge_entries,
                prompt_changes=prompt_changes,
                status="pending",
            )
            with self.get_session() as session:
                session.add(review)
                session.commit()
                return review.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create evolution review: {e}")

    def get_evolution_logs_by_agent(self, agent_id: int) -> list[EvolutionLog]:
        """Get evolution logs for an agent"""
        try:
            with self.get_session() as session:
                return session.query(EvolutionLog).filter(EvolutionLog.agent_id == agent_id).all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_evolution_logs", resource_id=agent_id, error=str(e))
            return []

    def update_evolution_applied(self, evolution_log_id: int) -> bool:
        """Mark evolution as applied"""
        try:
            with self.get_session() as session:
                evolution_log = (
                    session.query(EvolutionLog).filter(EvolutionLog.id == evolution_log_id).first()
                )
                if not evolution_log:
                    return False

                evolution_log.applied = True
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(
                "postgres_update_evolution_log", resource_id=evolution_log_id, error=str(e)
            )
            return False

    # ─── A2A Messages & Workflows ───────────────────────────────────

    def create_a2a_message(
        self,
        sender: str,
        recipients,
        task: str,
        task_type: str,
        company_id: int,
        payload: dict = None,
    ) -> str:
        """Create an A2A message"""
        import json
        import uuid

        from .models import A2AMessage

        message_id = uuid.uuid4().hex
        try:
            with self.get_session() as session:
                msg = A2AMessage(
                    message_id=message_id,
                    sender_agent_name=sender,
                    recipient_agent_name=json.dumps(recipients)
                    if isinstance(recipients, list)
                    else recipients,
                    task_description=task,
                    task_type=task_type,
                    payload=json.dumps(payload) if payload else None,
                    company_id=company_id,
                    status="pending",
                )
                session.add(msg)
                session.commit()
                return message_id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create A2A message: {e}")

    def update_a2a_message_status(self, message_id: str, status: str, result: str = None) -> bool:
        """Update A2A message status"""
        from .models import A2AMessage

        try:
            with self.get_session() as session:
                msg = session.query(A2AMessage).filter(A2AMessage.message_id == message_id).first()
                if not msg:
                    return False
                msg.status = status
                if result:
                    msg.result = result
                if status in ("completed", "failed"):
                    msg.completed_at = datetime.utcnow()
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_a2a_message", resource_id=message_id, error=str(e))
            return False

    def get_pending_a2a_messages(self) -> list[dict]:
        """Get all pending A2A messages"""
        import json

        from .models import A2AMessage

        try:
            with self.get_session() as session:
                msgs = session.query(A2AMessage).filter(A2AMessage.status == "pending").all()
                return [
                    {
                        "message_id": m.message_id,
                        "sender_agent_name": m.sender_agent_name,
                        "recipient_agent_name": m.recipient_agent_name,
                        "task_description": m.task_description,
                        "task_type": m.task_type,
                        "payload": json.loads(m.payload) if m.payload else {},
                        "company_id": m.company_id,
                        "status": m.status,
                        "result": m.result,
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in msgs
                ]
        except SQLAlchemyError as e:
            logger.error("postgres_get_pending_a2a_messages", error=str(e))
            return []

    def create_workflow(self, company_id: int, name: str, definition_json: str) -> int:
        """Create a new workflow"""
        from .models import Workflow

        try:
            with self.get_session() as session:
                workflow = Workflow(
                    company_id=company_id,
                    name=name,
                    definition_json=definition_json,
                    status="pending",
                )
                session.add(workflow)
                session.commit()
                return workflow.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create workflow: {e}")

    def get_workflow(self, workflow_id: int):
        """Get workflow by ID"""
        from .models import Workflow

        try:
            with self.get_session() as session:
                return session.query(Workflow).filter(Workflow.id == workflow_id).first()
        except SQLAlchemyError as e:
            logger.error("postgres_get_workflow", resource_id=workflow_id, error=str(e))
            return None

    def get_pending_workflows(self) -> list:
        """Get pending workflows for the background workflow worker."""
        from .models import Workflow

        try:
            with self.get_session() as session:
                return session.query(Workflow).filter(Workflow.status == "pending").all()
        except SQLAlchemyError as e:
            logger.error("postgres_get_pending_workflows", error=str(e))
            return []

    def get_workflow_status(self, workflow_id: int) -> dict | None:
        """Get workflow status as a serializable dictionary."""
        workflow = self.get_workflow(workflow_id)
        if not workflow:
            return None
        return {
            "id": workflow.id,
            "company_id": workflow.company_id,
            "name": workflow.name,
            "status": workflow.status,
            "definition_json": workflow.definition_json,
            "result_json": workflow.result_json,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            "completed_at": workflow.completed_at.isoformat() if workflow.completed_at else None,
        }

    def update_workflow_status(
        self, workflow_id: int, status: str, result_json: str = None
    ) -> bool:
        """Update workflow status and optionally store results"""
        from datetime import datetime

        from .models import Workflow

        try:
            with self.get_session() as session:
                workflow = session.query(Workflow).filter(Workflow.id == workflow_id).first()
                if not workflow:
                    return False
                workflow.status = status
                if result_json is not None:
                    workflow.result_json = result_json
                if status in ("completed", "failed"):
                    workflow.completed_at = datetime.utcnow()
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_workflow_status", resource_id=workflow_id, error=str(e))
            return False

    # ─── Company Credentials ────────────────────────────────────────

    def update_company_platform_credentials(self, company_id: int, credentials_json: str) -> bool:
        """Update company platform credentials"""
        try:
            with self.get_session() as session:
                company = session.query(Company).filter(Company.id == company_id).first()
                if not company:
                    return False
                company.platform_credentials = credentials_json
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_credentials", resource_id=company_id, error=str(e))
            return False

    def update_company_llm_config(self, company_id: int, config_json: str) -> bool:
        """Update company LLM config (multi-provider JSON, stored encrypted in llm_api_key column).

        复用 Company.llm_api_key (EncryptedText) 字段存储多厂商 LLM 配置 JSON，
        与 platform_credentials 同样享受 EncryptedText 透明加解密保护。
        """
        try:
            with self.get_session() as session:
                company = session.query(Company).filter(Company.id == company_id).first()
                if not company:
                    return False
                company.llm_api_key = config_json
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error("postgres_update_llm_config", resource_id=company_id, error=str(e))
            return False

    # ─── Subscription ───────────────────────────────────────────────

    def get_subscription_plans(self) -> list:
        """Get all subscription plans"""
        from .models import SubscriptionPlan

        try:
            with self.get_session() as session:
                plans = session.query(SubscriptionPlan).filter(SubscriptionPlan.is_active).all()
                # 过滤掉 _sa_instance_state 等 SQLAlchemy 内部字段，避免泄漏到 API 响应
                return [
                    {k: v for k, v in p.__dict__.items() if not k.startswith("_")} for p in plans
                ]
        except SQLAlchemyError as e:
            logger.error("postgres_get_subscription_plans", error=str(e))
            return []

    def get_subscription_plan(self, plan_id: int):
        """Get subscription plan by ID"""
        from .models import SubscriptionPlan

        try:
            with self.get_session() as session:
                plan = (
                    session.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
                )
                if plan:
                    # 过滤掉 _sa_instance_state 等 SQLAlchemy 内部字段，避免泄漏到 API 响应
                    return {k: v for k, v in plan.__dict__.items() if not k.startswith("_")}
                return None
        except SQLAlchemyError as e:
            logger.error("postgres_get_subscription_plan", resource_id=plan_id, error=str(e))
            return None

    def get_company_subscription_by_agent(self, company_id: int, agent_name: str):
        """Get company subscription by agent name"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = (
                    session.query(CompanySubscription)
                    .filter(
                        CompanySubscription.company_id == company_id,
                        CompanySubscription.agent_name == agent_name,
                        CompanySubscription.status == "active",
                    )
                    .first()
                )
                if sub:
                    # 过滤掉 _sa_instance_state 等 SQLAlchemy 内部字段，避免泄漏到 API 响应
                    return {k: v for k, v in sub.__dict__.items() if not k.startswith("_")}
                return None
        except SQLAlchemyError as e:
            logger.error("postgres_get_company_subscription", error=str(e))
            return None

    def get_company_subscription(self, subscription_id: int):
        """Get company subscription by ID"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = (
                    session.query(CompanySubscription)
                    .filter(CompanySubscription.id == subscription_id)
                    .first()
                )
                if sub:
                    # 过滤掉 _sa_instance_state 等 SQLAlchemy 内部字段，避免泄漏到 API 响应
                    return {k: v for k, v in sub.__dict__.items() if not k.startswith("_")}
                return None
        except SQLAlchemyError as e:
            logger.error(
                "postgres_get_company_subscription", resource_id=subscription_id, error=str(e)
            )
            return None

    def create_company_subscription(
        self, company_id: int, plan_id: int, agent_name: str, status: str = "active", end_date=None
    ) -> int:
        """Create a new company subscription"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = CompanySubscription(
                    company_id=company_id,
                    plan_id=plan_id,
                    agent_name=agent_name,
                    status=status,
                    end_date=end_date,
                    start_date=datetime.utcnow(),
                )
                session.add(sub)
                session.commit()
                return sub.id
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to create company subscription: {e}")

    def update_company_subscription_status(self, company_id: int, status: str) -> bool:
        """Update company subscription status"""
        try:
            with self.get_session() as session:
                company = session.query(Company).filter(Company.id == company_id).first()
                if not company:
                    return False
                company.subscription_status = status
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(
                "postgres_update_subscription_status", resource_id=company_id, error=str(e)
            )
            return False

    def get_company_active_subscriptions(self, company_id: int) -> list:
        """Get all active subscriptions for a company"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                subs = (
                    session.query(CompanySubscription)
                    .filter(
                        CompanySubscription.company_id == company_id,
                        CompanySubscription.status == "active",
                    )
                    .all()
                )
                # 过滤掉 _sa_instance_state 等 SQLAlchemy 内部字段，避免泄漏到 API 响应
                return [
                    {k: v for k, v in s.__dict__.items() if not k.startswith("_")} for s in subs
                ]
        except SQLAlchemyError as e:
            logger.error("postgres_get_active_subscriptions", resource_id=company_id, error=str(e))
            return []

    def extend_subscription_end_date(self, subscription_id: int, months: int) -> bool:
        """Extend a subscription's end_date by the given number of months"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = (
                    session.query(CompanySubscription)
                    .filter(CompanySubscription.id == subscription_id)
                    .first()
                )
                if not sub:
                    return False
                # end_date 为空时从当前时间开始计算，否则在现有 end_date 基础上延长
                base_date = sub.end_date if sub.end_date else datetime.utcnow()
                # 按月延长：近似为 30 天/月，避免引入 dateutil 依赖
                from datetime import timedelta

                sub.end_date = base_date + timedelta(days=30 * months)
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(
                "postgres_extend_subscription_end_date", resource_id=subscription_id, error=str(e)
            )
            return False

    def update_subscription_auto_renew(self, subscription_id: int, auto_renew: bool) -> bool:
        """Update a subscription's auto_renew flag"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = (
                    session.query(CompanySubscription)
                    .filter(CompanySubscription.id == subscription_id)
                    .first()
                )
                if not sub:
                    return False
                sub.auto_renew = auto_renew
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(
                "postgres_update_subscription_auto_renew", resource_id=subscription_id, error=str(e)
            )
            return False

    def update_subscription_status(self, subscription_id: int, status: str) -> bool:
        """Update a subscription's status (e.g. active / cancelled / expired)"""
        from .models import CompanySubscription

        try:
            with self.get_session() as session:
                sub = (
                    session.query(CompanySubscription)
                    .filter(CompanySubscription.id == subscription_id)
                    .first()
                )
                if not sub:
                    return False
                sub.status = status
                session.commit()
                return True
        except SQLAlchemyError as e:
            logger.error(
                "postgres_update_subscription_status", resource_id=subscription_id, error=str(e)
            )
            return False


class ConnectionContext:
    """Context manager for backward compatibility with old code using 'with db.get_connection() as conn:'"""

    def __init__(self, engine):
        self.engine = engine
        self.connection = None

    def __enter__(self):
        # 返回 self 而非 raw connection，使调用方可以使用本类提供的 execute 方法
        # 之前返回 raw connection 会导致本类的 execute 方法无法被调用（with...as 拿到的是 connection 而非 context）
        self.connection = self.engine.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
        return False

    def execute(self, query: str, params: dict = None):
        """Execute SQL query (for backward compatibility)

        使用内部 connection 执行 SQL。params 推荐使用命名参数字典，
        与 SQLAlchemy text() 命名参数风格一致。
        """
        if not self.connection:
            raise RuntimeError("No active database connection")

        try:
            if params:
                result = self.connection.execute(text(query), params)
            else:
                result = self.connection.execute(text(query))

            # For SELECT queries, return results
            if result.returns_rows:
                return result.fetchall()
            else:
                return result.rowcount if result.rowcount else 0
        except Exception as e:
            logger.error("postgres_execute_query", error=str(e))
            raise
