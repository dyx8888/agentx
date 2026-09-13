"""
Workflow Engine for A2A Protocol
Executes predefined workflows with dependency resolution and node management
"""

import json
import os
import re
import threading
from datetime import datetime
from inspect import isawaitable

from app.agent import get_agent_for_tools
from app.core.logging import get_logger
from app.database import db
from app.workflow.a2a_schema import WorkflowDefinition

logger = get_logger(__name__)


def _run_maybe_async(result):
    """Resolve direct MCP helper calls that may return a coroutine."""
    if not isawaitable(result):
        return result

    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(result)

    raise RuntimeError("Cannot run async workflow tool from an active event loop")


class WorkflowEngine:
    """Engine for executing A2A workflow DAGs"""

    def __init__(self):
        self.running = False
        self.worker_thread = None
        self.current_workflows = {}  # workflow_id -> WorkflowDefinition
        self.workflow_results = {}  # workflow_id -> results

    def start(self):
        """Start the workflow engine"""
        self.running = True
        self.worker_thread = threading.Thread(target=self._process_workflows, daemon=True)
        self.worker_thread.start()
        logger.info("Workflow engine started")

    def stop(self):
        """Stop the workflow engine"""
        self.running = False
        if self.worker_thread:
            # Wait a bit for current processing to finish
            self.worker_thread.join(timeout=5)
            self.worker_thread = None
        logger.info("Workflow engine stopped")

    def submit_workflow(self, company_id: int, name: str, definition_json: str) -> str:
        """
        Submit a new workflow definition

        Args:
            company_id: Company ID for multi-tenant isolation
            name: Workflow name
            definition_json: JSON definition of workflow DAG

        Returns:
            Workflow ID
        """
        try:
            # Create workflow record
            workflow_id = db.create_workflow(company_id, name, definition_json)

            # Parse and store workflow definition
            workflow_def = WorkflowDefinition(
                id=workflow_id,
                company_id=company_id,
                name=name,
                definition_json=definition_json,
                status="pending",
            )

            self.current_workflows[workflow_id] = workflow_def
            logger.info(f"Workflow submitted: {name} (ID: {workflow_id})")

            return f"Workflow '{name}' submitted. ID: {workflow_id}"

        except Exception as e:
            logger.error(f"Error submitting workflow: {e}")
            return f"Error submitting workflow: {e}"

    def _process_workflows(self):
        """Main processing loop for workflows"""
        while self.running:
            try:
                # Get all pending workflows
                pending_workflows = db.get_pending_workflows()

                for workflow in pending_workflows:
                    if workflow.id not in self.current_workflows:
                        # Load workflow definition
                        self.current_workflows[workflow.id] = workflow

                        # Process workflow
                        self._execute_workflow(workflow)

                # Sleep before next iteration
                threading.Event().wait(3)  # 3-second polling interval

            except Exception as e:
                logger.error(f"Error in workflow processing: {e}")
                threading.Event().wait(10)  # Wait longer on error

    def _execute_workflow(self, workflow: WorkflowDefinition):
        """Execute a single workflow DAG"""
        try:
            logger.info(f"Executing workflow: {workflow.name}")

            # Parse workflow definition
            workflow_data = json.loads(workflow.definition_json)
            nodes = workflow_data.get("nodes", [])

            # Create execution context
            execution_context = {
                "workflow_id": workflow.id,
                "company_id": workflow.company_id,
                "started_at": datetime.utcnow().isoformat(),
                "nodes": {},
                "completed_nodes": [],
                "pending_nodes": [node["id"] for node in nodes],
                "results": {},
            }

            # Execute nodes in dependency order.
            while execution_context["pending_nodes"]:
                progress_made = False
                for node_id in execution_context["pending_nodes"][:]:  # Process in order
                    node = next((n for n in nodes if n["id"] == node_id), None)
                    if not node:
                        logger.error(f"Node {node_id} not found in workflow definition")
                        execution_context["pending_nodes"].remove(node_id)
                        execution_context["results"][node_id] = "Error: node not found"
                        progress_made = True
                        continue

                    # Check dependencies
                    if self._check_dependencies(node, execution_context):
                        # Store message
                        message_id = db.create_a2a_message(
                            sender=node["agent"],
                            recipients=[node.get("agent", "")],
                            task=node.get("description", ""),
                            task_type=node.get("action", ""),
                            company_id=workflow.company_id,
                            payload=node.get("params", {}),
                        )

                        # Update message status to processing
                        db.update_a2a_message_status(message_id, "processing")

                        # Execute action
                        result = self._execute_node(node, execution_context)
                        stored_result = self._serialize_result(result)

                        # Update message status and result
                        db.update_a2a_message_status(
                            message_id, "completed", result_json=stored_result
                        )

                        # Update execution context
                        execution_context["completed_nodes"].append(node_id)
                        execution_context["pending_nodes"].remove(node_id)
                        execution_context["results"][node_id] = stored_result
                        execution_context[node_id] = {
                            "result": self._context_result(node["action"], result)
                        }
                        progress_made = True

                        logger.info(f"Node {node_id} completed: {stored_result}")

                if not progress_made:
                    pending = execution_context["pending_nodes"]
                    error = f"Workflow dependency deadlock. Pending nodes: {pending}"
                    logger.error(error)
                    db.update_workflow_status(
                        workflow.id,
                        "failed",
                        json.dumps(
                            {"error": error, "results": execution_context["results"]},
                            ensure_ascii=False,
                        ),
                    )
                    break

            # Update workflow status
            if not execution_context["pending_nodes"]:
                db.update_workflow_status(
                    workflow.id,
                    "completed",
                    json.dumps(execution_context["results"], ensure_ascii=False),
                )
                logger.info(f"Workflow {workflow.name} completed successfully")
            else:
                logger.warning(
                    f"Workflow {workflow.name} completed with pending nodes: {execution_context['pending_nodes']}"
                )

        except Exception as e:
            logger.error(f"Error executing workflow {workflow.name}: {e}")

    def _check_dependencies(self, node: dict, context: dict) -> bool:
        """Check if all dependencies are completed"""
        depends_on = node.get("depends_on", [])

        return all(dep_id in context["completed_nodes"] for dep_id in depends_on)

    def _execute_node(self, node: dict, context: dict) -> str:
        """Execute a single workflow node"""
        try:
            agent_name = node["agent"]
            action = node["action"]
            params = self._resolve_node_params(node.get("params", {}), context)

            agent_instance = self._get_agent_instance(agent_name)

            # Execute action
            if action == "search_kols":
                return self._execute_search_kols_action(agent_instance, params, context)
            elif action == "generate_outreach":
                return self._execute_generate_outreach_action(agent_instance, params, context)
            elif action == "generate_performance_report":
                return self._execute_generate_performance_report_action(
                    agent_instance, params, context
                )
            elif action == "generate_strategy_suggestion":
                return self._execute_generate_strategy_suggestion_action(
                    agent_instance, params, context
                )
            elif action == "generate_script":
                return self._execute_generate_script_action(agent_instance, params, context)
            elif action == "check_delivery_status":
                return self._execute_check_delivery_status_action(agent_instance, params, context)
            elif action == "generate_arrival_script":
                return self._execute_generate_arrival_script_action(
                    agent_instance, params, context
                )
            else:
                return f"Unknown action: {action}"

        except Exception as e:
            logger.error(f"Error executing node {node['id']}: {e}")
            return f"Error: {e}"

    def _get_agent_instance(self, agent_name: str):
        """Build an agent/tool proxy when available, but allow deterministic fallback."""
        try:
            agent_instance, _ = get_agent_for_tools(agent_name)
            return agent_instance
        except Exception as e:
            logger.warning("workflow_agent_build_failed", agent_name=agent_name, error=str(e))
            return None

    def _resolve_node_params(self, params: dict, context: dict) -> dict:
        """Resolve {{node.result.field}} placeholders immediately before node execution."""
        if not params:
            return {}
        try:
            params_json = json.dumps(params, ensure_ascii=False)
            resolved_json = self._replace_template_variables(params_json, context)
            return json.loads(resolved_json)
        except Exception as e:
            logger.warning("workflow_param_resolution_failed", error=str(e))
            return params

    def _serialize_result(self, result) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False)

    def _context_result(self, action: str, result):
        """Shape node results for downstream template variables."""
        parsed = result
        if isinstance(result, str):
            try:
                parsed = json.loads(result)
            except json.JSONDecodeError:
                return {"raw": result}

        if isinstance(parsed, dict) and parsed.get("status") == "ok":
            data = parsed.get("data")
            if action == "search_kols" and isinstance(data, list):
                first = data[0] if data else {}
                if isinstance(first, dict):
                    return {"items": data, **first}
            if isinstance(data, dict):
                return data
            return {"raw": data}

        if action == "search_kols" and isinstance(parsed, dict):
            data = parsed.get("data")
            if isinstance(data, list):
                first = data[0] if data else {}
                if isinstance(first, dict):
                    return {"items": data, **first}

        if isinstance(parsed, dict):
            return parsed
        return {"raw": parsed}

    def _call_agent_or_fallback(self, agent, method_name: str, fallback, **kwargs):
        """Call a mocked/real agent method first, then deterministic backend helper."""
        method = getattr(agent, method_name, None) if agent is not None else None
        if callable(method):
            return method(**kwargs)
        return _run_maybe_async(fallback(**kwargs))

    def _execute_search_kols_action(self, agent, params: dict, context: dict) -> str:
        """Execute search_kols action"""
        try:
            category = params.get("category", "beauty")
            count = params.get("count", 3)

            from app.mcp_servers.kol_search_server import search_kols

            return self._call_agent_or_fallback(
                agent,
                "search_kols",
                search_kols,
                category=category,
                count=count,
                company_id=context.get("company_id"),
            )

        except Exception as e:
            logger.error(f"Error in search_kols action: {e}")
            return f"Error: {e}"

    def _execute_generate_outreach_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_outreach action"""
        try:
            kol_name = params.get("kol_name", "")
            product_name = params.get("product_name", "")
            style = params.get("style", "professional")

            from app.mcp_servers.outreach_server import generate_outreach

            return self._call_agent_or_fallback(
                agent,
                "generate_outreach",
                generate_outreach,
                kol_name=kol_name,
                product_name=product_name,
                style=style,
            )

        except Exception as e:
            logger.error(f"Error in generate_outreach action: {e}")
            return f"Error: {e}"

    def _execute_generate_script_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_script action"""
        try:
            kol_name = params.get("kol_name", "")
            product_name = params.get("product_name", "")
            platform = params.get("platform", "douyin")
            style = params.get("style", "lively")

            from app.mcp_servers.script_server import generate_script

            return self._call_agent_or_fallback(
                agent,
                "generate_script",
                generate_script,
                kol_name=kol_name,
                product_name=product_name,
                platform=platform,
                style=style,
            )

        except Exception as e:
            logger.error(f"Error in generate_script action: {e}")
            return f"Error: {e}"

    def _execute_check_delivery_status_action(self, agent, params: dict, context: dict) -> str:
        """Execute check_delivery_status action"""
        try:
            order_id = params.get("order_id") or params.get("sample_id") or ""

            from app.mcp_servers.monitor_server import check_delivery_status

            return self._call_agent_or_fallback(
                agent,
                "check_delivery_status",
                check_delivery_status,
                order_id=order_id,
            )

        except TypeError:
            try:
                method = getattr(agent, "check_delivery_status", None)
                if callable(method):
                    return method(params.get("order_id") or params.get("sample_id") or "")
            except Exception as e:
                logger.error(f"Error in check_delivery_status compatibility call: {e}")
            return "Error: check_delivery_status call failed"
        except Exception as e:
            logger.error(f"Error in check_delivery_status action: {e}")
            return f"Error: {e}"

    def _execute_generate_arrival_script_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_arrival_script action"""
        try:
            kol_name = params.get("kol_name", "")
            product_name = params.get("product_name", "")
            delivery_status = params.get("delivery_status", "")

            from app.mcp_servers.monitor_server import generate_arrival_script

            return self._call_agent_or_fallback(
                agent,
                "generate_arrival_script",
                generate_arrival_script,
                kol_name=kol_name,
                product_name=product_name,
                delivery_status=delivery_status,
            )

        except Exception as e:
            logger.error(f"Error in generate_arrival_script action: {e}")
            return f"Error: {e}"

    def _execute_generate_performance_report_action(
        self, agent, params: dict, context: dict
    ) -> str:
        """Execute generate_performance_report action"""
        try:
            kol_name = params.get("kol_name", "")
            campaign_id = params.get("campaign_id", "")

            from app.mcp_servers.report_server import generate_performance_report

            return self._call_agent_or_fallback(
                agent,
                "generate_performance_report",
                generate_performance_report,
                kol_name=kol_name,
                campaign_id=campaign_id,
            )

        except Exception as e:
            logger.error(f"Error in generate_performance_report action: {e}")
            return f"Error: {e}"

    def _execute_generate_strategy_suggestion_action(
        self, agent, params: dict, context: dict
    ) -> str:
        """Execute generate_strategy_suggestion action"""
        try:
            platform = params.get("platform", "xiaohongshu")
            category = params.get("category", "beauty")

            from app.mcp_servers.report_server import generate_strategy_suggestion

            return self._call_agent_or_fallback(
                agent,
                "generate_strategy_suggestion",
                generate_strategy_suggestion,
                platform=platform,
                category=category,
            )

        except Exception as e:
            logger.error(f"Error in generate_strategy_suggestion action: {e}")
            return f"Error: {e}"

    def get_workflow_status(self, workflow_id: int) -> dict | None:
        """Get workflow execution status"""
        try:
            workflow = db.get_workflow(workflow_id)
            if not workflow:
                return None

            # Get related A2A messages
            messages = db.get_pending_a2a_messages(workflow.company_id)
            workflow_messages = [
                msg
                for msg in messages
                if msg.get("task_description", "").startswith(f"Workflow {workflow.name}")
            ]

            return {
                "workflow": {
                    "id": workflow.id,
                    "name": workflow.name,
                    "status": workflow.status,
                    "created_at": workflow.created_at.isoformat(),
                    "completed_at": workflow.completed_at.isoformat(),
                },
                "messages": workflow_messages,
                "results": json.loads(workflow.result_json) if workflow.result_json else {},
            }

        except Exception as e:
            logger.error(f"Error getting workflow status: {e}")
            return None

    def load_workflow_template(self, template_name: str) -> dict:
        """
        Load workflow template from JSON file

        Args:
            template_name: Name of the template file (without .json extension)

        Returns:
            Dictionary containing the workflow template

        Raises:
            FileNotFoundError: If template file doesn't exist
            json.JSONDecodeError: If template file is not valid JSON
        """
        try:
            template_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
                "config",
                "workflows",
                f"{template_name}.json",
            )

            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Workflow template not found: {template_path}")

            with open(template_path, encoding="utf-8") as f:
                template_data = json.load(f)

            logger.info(f"Loaded workflow template: {template_name}")
            return template_data

        except FileNotFoundError:
            raise FileNotFoundError(
                f"Workflow template '{template_name}' not found in config/workflows/"
            )
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Invalid JSON in workflow template '{template_name}': {e.msg}", e.doc, e.pos
            ) from e
        except Exception as e:
            raise Exception(f"Error loading workflow template '{template_name}': {e}")

    def _replace_template_variables(self, template_str: str, context: dict) -> str:
        """
        Replace template variables with context values

        Supports simple variables like {{category}} and nested variables
        with dot notation like {{node.result.field}}.

        Args:
            template_str: Template string with {{variable}} placeholders
            context: Dictionary of variable values

        Returns:
            String with variables replaced
        """
        try:

            def resolve_placeholder(match):
                # Split dot-notation path and walk the context dict
                keys = match.group(1).split(".")
                value = context
                for key in keys:
                    if isinstance(value, dict) and key in value:
                        value = value[key]
                    else:
                        # Path cannot be resolved, keep original placeholder
                        return match.group(0)
                return str(value)

            return re.sub(r"\{\{([^{}]+)\}\}", resolve_placeholder, template_str)

        except Exception as e:
            logger.error(f"Error replacing template variables: {e}")
            return template_str

    def execute_brand_bd_workflow(self, company_id: int, context: dict) -> str:
        """
        Execute brand BD workflow with template and context

        Args:
            company_id: Company ID for multi-tenant isolation
            context: Dictionary containing variables like category, product_name, order_id, campaign_id

        Returns:
            Workflow ID string
        """
        try:
            # Load template
            template = self.load_workflow_template("brand_bd_workflow")

            # Convert template to JSON string for variable replacement
            template_json = json.dumps(template)

            # Replace template variables with context values
            definition_json = self._replace_template_variables(template_json, context)

            # Submit workflow to database
            workflow_id = db.create_workflow(company_id, template["name"], definition_json)

            # Parse and store workflow definition
            workflow_def = WorkflowDefinition(
                id=workflow_id,
                company_id=company_id,
                name=template["name"],
                definition_json=definition_json,
                status="pending",
            )

            self.current_workflows[workflow_id] = workflow_def
            logger.info(f"Brand BD workflow submitted: {template['name']} (ID: {workflow_id})")

            # Trigger workflow execution
            self._execute_workflow(workflow_def)

            return str(workflow_id)

        except Exception as e:
            logger.error(f"Error executing brand BD workflow: {e}")
            return f"Error executing brand BD workflow: {e}"
