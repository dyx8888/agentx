"""
Task Worker - Background Task Processing
Handles asynchronous task execution in separate thread
Supports both Redis queue consumption and database polling
"""

import asyncio
import json
import threading
import time
import uuid

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import get_logger
from app.database import db

# Try to import Redis queue
try:
    from app.messaging.redis_queue import get_redis_queue, is_redis_available
except ImportError:
    get_redis_queue = None
    is_redis_available = None

logger = get_logger(__name__)

class TaskWorker:
    """Background task worker that processes tasks asynchronously"""

    def __init__(self, poll_interval: int = 5):
        self.poll_interval = poll_interval
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.is_running = False
        self.use_redis = False
        self.redis_queue = None

        if is_redis_available and is_redis_available():
            self.redis_queue = get_redis_queue()
            if self.redis_queue and self.redis_queue.is_available():
                self.use_redis = True
                logger.info("TaskWorker configured for Redis queue consumption")
            else:
                logger.warning("Redis available but queue not ready, falling back to database polling")
        else:
            logger.info("TaskWorker configured for database polling")

    def start(self):
        """Start the worker thread"""
        if self.is_running:
            logger.warning("task_worker_already_running")
            return

        self.is_running = True
        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self._run, daemon=True)
        self.worker_thread.start()
        logger.info("task_worker_started")

    def stop(self):
        """Stop the worker thread"""
        if not self.is_running:
            return

        self.is_running = False
        self.stop_event.set()

        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=10)

        logger.info("task_worker_stopped")

    def _run(self):
        """Main worker loop"""
        if self.use_redis:
            logger.info("TaskWorker started in Redis queue consumption mode")
            self._run_redis_mode()
        else:
            logger.info(f"TaskWorker started with {self.poll_interval}s poll interval")
            self._run_database_mode()

    def _run_redis_mode(self):
        """Run in Redis queue consumption mode"""
        if not self.redis_queue:
            logger.error("Redis queue not available, cannot run in Redis mode")
            return

        try:
            # Define task processing callback
            def process_redis_task(task_data):
                self._process_single_task(task_data)

            # Start consuming tasks from Redis
            self.redis_queue.consume_tasks(process_redis_task)

        except Exception as e:
            logger.error(f"Error in Redis mode: {e}")

    def _run_database_mode(self):
        """Run in database polling mode"""
        while self.is_running and not self.stop_event.is_set():
            try:
                self._process_pending_tasks()

                # Wait for next poll or stop signal
                self.stop_event.wait(self.poll_interval)

            except Exception as e:
                logger.error(f"Error in TaskWorker main loop: {e}")
                # Continue running even if there's an error
                time.sleep(self.poll_interval)

    def _process_pending_tasks(self):
        """Process all pending tasks"""
        try:
            pending_tasks = db.get_pending_tasks()

            if not pending_tasks:
                return

            logger.info("processing_pending_tasks", task_count=len(pending_tasks))

            for task in pending_tasks:
                self._process_single_task(task)

        except Exception as e:
            logger.error("task_worker_processing_error", error=str(e))

    def _process_single_task(self, task: dict):
        """Process a single task with AgentRuntime Plan-Execute-Reflect."""
        task_request_id = f"task-{uuid.uuid4().hex[:12]}"

        if 'id' in task:
            task_id = task['id']
            company_id = task['company_id']
            source_agent_id = task['source_agent_id']
            target_agent_name = task['target_agent_name']
            task_description = task['task_description']
            db.update_task_status(task_id, 'processing')
        else:
            task_id = task.get('task_id', f"redis_{int(time.time())}")
            company_id = task.get('company_id')
            source_agent_id = task.get('source_agent_id')
            target_agent_name = task.get('target_agent_name')
            task_description = task.get('task_description')

        structlog.contextvars.bind_contextvars(
            request_id=task_request_id,
            task_id=task_id,
            company_id=company_id,
        )

        try:
            logger.info(f"Processing task {task_id}: {target_agent_name} - {task_description[:50]}...")

            self._notify_task_started(company_id, task_id, target_agent_name, task_description)

            from app.agents import create_agent_execution_context
            exec_context = create_agent_execution_context(
                agent_key=target_agent_name,
                company_id=company_id,
                task_description=task_description,
            )

            target_agent = db.get_agent_by_name(target_agent_name)
            if not target_agent:
                raise Exception(f"Target agent '{target_agent_name}' not found")

            if target_agent.company_id != company_id:
                raise Exception(f"Agent '{target_agent_name}' does not belong to company {company_id}")

            import json
            tool_names = json.loads(target_agent.tools_json)

            from app.agent import build_reaction_graph, build_system_message, State
            from app.services.model_gateway import get_global_model_gateway
            from app.tools.registry import registry

            mg = get_global_model_gateway()
            llm = mg.get_llm()
            tools = registry.get_tools_by_names(tool_names)
            llm_with_tools = llm.bind_tools(tools)

            def agent(state: State):
                messages = state["messages"]
                company_context = state.get("company_context", {})
                system_message = build_system_message(company_context)
                messages_with_system = [SystemMessage(content=system_message)] + messages
                response = llm_with_tools.invoke(messages_with_system)
                return {"messages": [response]}

            target_agent_app, _ = build_reaction_graph(agent, tools, mg)

            rag_context = exec_context.get("rag_context", "")
            enhanced_task = task_description
            if rag_context:
                enhanced_task = (
                    f"【公司上下文】\n{rag_context}\n\n"
                    f"【任务指令】\n{task_description}"
                )

            state = {
                "messages": [HumanMessage(content=enhanced_task)],
                "company_context": {
                    "company_id": company_id,
                    "source_agent_id": source_agent_id,
                    "task_mode": "async",
                    "agent_key": target_agent_name,
                }
            }

            result = self._execute_with_timeout(target_agent_app, state, timeout=300)

            steps = self._extract_steps(result)

            for step in steps:
                if step['name'] in ['generate_outreach', 'generate_script', 'generate_strategy_suggestion']:
                    step['status'] = 'confirm_required'
                    self._save_task_steps(task_id, steps)
                    db.update_task_status(task_id, 'waiting_confirmation')
                    logger.info(f"Task {task_id} paused at step {step['name']} for human confirmation")
                    self._notify_review_required(company_id, task_id, target_agent_name, step)
                    return

            if 'id' in task:
                db.update_task_status(task_id, 'completed', result)

            logger.info(f"Task {task_id} completed successfully")

            self._notify_task_completed(company_id, task_id, target_agent_name, result)

            try:
                from app.communication.collaboration import collaboration_engine
                if target_agent_name and company_id:
                    asyncio = self._get_async_loop()
                    asyncio.run_coroutine_threadsafe(
                        collaboration_engine.on_agent_task_completed(
                            agent_key=target_agent_name,
                            company_id=company_id,
                            task_id=task_id,
                            result_summary=str(result)[:500],
                        ),
                        asyncio,
                    )
            except Exception as e:
                logger.error(f"[COLLABORATION] Error processing collaboration: {e}")

            try:
                from app.evolution.suggester import EvolutionSuggester
                target_agent = db.get_agent_by_name(target_agent_name)
                agent_id = target_agent.id if target_agent else None

                if agent_id:
                    suggester = EvolutionSuggester()
                    suggestion = suggester.generate_lightweight_suggestion(agent_id, result)

                    if suggestion.confidence_score >= 0.3:
                        db.create_evolution_review(
                            agent_id=agent_id,
                            tool_name=suggestion.tool_name if hasattr(suggestion, 'tool_name') else None,
                            suggestion_text=suggestion.suggested_prompt_changes or suggestion.analysis_summary,
                            knowledge_entries=str(suggestion.knowledge_entries) if suggestion.knowledge_entries else None,
                            prompt_changes=suggestion.suggested_prompt_changes
                        )
                        logger.info(f"[EVOLUTION] Real-time suggestion generated for agent {agent_id}, confidence: {suggestion.confidence_score:.2f}")
            except Exception as e:
                logger.error(f"[EVOLUTION] Real-time evolution trigger failed (non-blocking): {e}")

        except Exception as e:
            error_msg = f"Task execution failed: {str(e)}"
            logger.error(f"Task {task_id} failed: {error_msg}")

            if 'id' in task:
                db.update_task_status(task_id, 'failed', error_msg)

            self._notify_task_failed(company_id, task_id, target_agent_name, error_msg)
        finally:
            structlog.contextvars.clear_contextvars()

    def _execute_with_timeout(self, agent_app, state: dict, timeout: int = 300) -> str:
        """Execute agent with timeout"""
        import threading

        result_container = {}
        exception_container = []

        def target():
            try:
                result = agent_app.invoke(state)
                if result and result.get("messages"):
                    result_container['value'] = result["messages"][-1].content
                else:
                    result_container['value'] = "Task completed but no response generated"
            except Exception as e:
                exception_container.append(e)

        thread = threading.Thread(target=target)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            raise TimeoutError(f"Task execution timed out after {timeout} seconds")

        if exception_container:
            raise exception_container[0]

        return result_container.get('value', 'No result generated')

    def _notify_task_started(self, company_id: int, task_id: int, agent_key: str,
                               description: str):
        try:
            from app.ws import ws_manager
            asyncio = self._get_async_loop()
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_task_status(company_id, task_id, "processing", agent_key),
                asyncio,
            )
        except Exception:
            pass

    def _notify_task_completed(self, company_id: int, task_id: int, agent_key: str,
                                 result: str):
        try:
            from app.ws import ws_manager
            asyncio = self._get_async_loop()
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_to_company(company_id, {
                    "type": "task_status",
                    "taskId": task_id,
                    "status": "completed",
                    "agent": agent_key,
                    "summary": str(result)[:200],
                }),
                asyncio,
            )
        except Exception:
            pass

    def _notify_task_failed(self, company_id: int, task_id: int, agent_key: str,
                              error_msg: str):
        try:
            from app.ws import ws_manager
            asyncio = self._get_async_loop()
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_task_status(company_id, task_id, "failed", agent_key),
                asyncio,
            )
        except Exception:
            pass

    def _notify_review_required(self, company_id: int, task_id: int, agent_key: str,
                                  step: dict):
        try:
            from app.ws import ws_manager
            asyncio = self._get_async_loop()
            asyncio.run_coroutine_threadsafe(
                ws_manager.broadcast_review_notification(
                    company_id, task_id, agent_key, "mandatory"
                ),
                asyncio,
            )
        except Exception:
            pass

    def _get_async_loop(self):
        try:
            return asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop

# Global worker instance
_global_worker: TaskWorker | None = None

def get_task_worker() -> TaskWorker:
    """Get or create global task worker instance"""
    global _global_worker
    if _global_worker is None:
        _global_worker = TaskWorker()
    return _global_worker

def start_task_worker():
    """Start the global task worker"""
    worker = get_task_worker()
    worker.start()

def stop_task_worker():
    """Stop the global task worker"""
    global _global_worker
    if _global_worker:
        _global_worker.stop()

def _extract_steps(result: str) -> list:
    """
    Extract execution steps from agent result
    Convert LangChain objects to serializable format
    """
    steps = []

    try:
        # Try to parse as JSON first
        if isinstance(result, str):
            parsed_result = json.loads(result)
            if isinstance(parsed_result, dict) and 'steps' in parsed_result:
                steps = parsed_result['steps']
            elif isinstance(parsed_result, list):
                steps = parsed_result
        elif isinstance(result, dict):
            if 'steps' in result:
                steps = result['steps']
            else:
                steps = []
        else:
            steps = []

        # Ensure all steps have required fields
        formatted_steps = []
        for i, step in enumerate(steps):
            if isinstance(step, dict):
                formatted_step = {
                    'step_id': i + 1,
                    'name': step.get('name', f'Step {i + 1}'),
                    'status': step.get('status', 'pending'),
                    'result': step.get('result', None)
                }
            else:
                formatted_step = {
                    'step_id': i + 1,
                    'name': str(step),
                    'status': 'completed',
                    'result': str(step)
                }
            formatted_steps.append(formatted_step)

        return formatted_steps

    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning(f"Error extracting steps from result: {e}")
        # Fallback: create a single step with the result
        return [{
            'step_id': 1,
            'name': 'Task Execution',
            'status': 'completed',
            'result': str(result) if result else 'No result generated'
        }]

def _save_task_steps(task_id: int, steps: list):
    """
    Save steps list to task.result field as JSON
    """
    try:
        steps_json = json.dumps({'steps': steps})
        db.update_task_status(task_id, 'processing', steps_json)
        logger.info(f"Saved {len(steps)} steps for task {task_id}")
    except Exception as e:
        logger.error(f"Error saving task steps: {e}")
        # Fallback: save as simple string
        db.update_task_status(task_id, 'processing', str(steps))
