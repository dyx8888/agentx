"""
Workflow Engine for A2A Protocol
Executes predefined workflows with dependency resolution and node management
"""

import json
import os
import threading
from datetime import datetime

from langchain_core.messages import SystemMessage

from app.agent import build_reaction_graph, get_agent_by_name, build_system_message, State
from app.core.logging import get_logger
from app.database import db
from app.services.model_gateway import get_global_model_gateway
from app.tools.registry import registry
from app.workflow.a2a_schema import WorkflowDefinition

logger = get_logger(__name__)

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
                status="pending"
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
                "results": {}
            }

            # Execute nodes in order (simplified linear execution)
            while execution_context["pending_nodes"]:
                for node_id in execution_context["pending_nodes"][:]:  # Process in order
                    node = next((n for n in nodes if n["id"] == node_id), None)
                    if not node:
                        logger.error(f"Node {node_id} not found in workflow definition")
                        continue

                    # Check dependencies
                    if self._check_dependencies(node, execution_context):
                        # Execute node
                        result = self._execute_node(node, execution_context)



                        # Store message
                        message_id = db.create_a2a_message(
                            sender=node["agent"],
                            recipients=[node.get("agent", "")],
                            task=node.get("description", ""),
                            task_type=node.get("action", ""),
                            company_id=workflow.company_id,
                            payload=node.get("params", {})
                        )

                        # Update message status to processing
                        db.update_a2a_message_status(message_id, "processing")

                        # Execute action
                        if node["action"] == "search_kols":
                            result = self._execute_search_kols(node, execution_context)
                        elif node["action"] == "generate_outreach":
                            result = self._execute_generate_outreach(node, execution_context)
                        elif node["action"] == "generate_performance_report":
                            result = self._execute_generate_performance_report(node, execution_context)
                        elif node["action"] == "generate_strategy_suggestion":
                            result = self._execute_generate_strategy_suggestion(node, execution_context)
                        else:
                            result = f"Unknown action: {node['action']}"

                        # Update message status and result
                        db.update_a2a_message_status(message_id, "completed", result_json=result)

                        # Update execution context
                        execution_context["completed_nodes"].append(node_id)
                        execution_context["pending_nodes"].remove(node_id)
                        execution_context["results"][node_id] = result

                        logger.info(f"Node {node_id} completed: {result}")

            # Update workflow status
            if not execution_context["pending_nodes"]:
                db.update_workflow_status(workflow.id, "completed", json.dumps(execution_context["results"]))
                logger.info(f"Workflow {workflow.name} completed successfully")
            else:
                logger.warning(f"Workflow {workflow.name} completed with pending nodes: {execution_context['pending_nodes']}")

        except Exception as e:
            logger.error(f"Error executing workflow {workflow.name}: {e}")

    def _check_dependencies(self, node: dict, context: dict) -> bool:
        """Check if all dependencies are completed"""
        depends_on = node.get("depends_on", [])

        for dep_id in depends_on:
            if dep_id not in context["completed_nodes"]:
                return False

        return True

    def _execute_node(self, node: dict, context: dict) -> str:
        """Execute a single workflow node"""
        try:
            agent_name = node["agent"]
            action = node["action"]
            params = node.get("params", {})

            system_prompt, default_tools = get_agent_by_name(agent_name)
            model_gateway = get_global_model_gateway()
            llm = model_gateway.get_llm()
            tools = registry.get_tools_by_names(default_tools)
            llm_with_tools = llm.bind_tools(tools)

            def agent(state: State):
                messages = state["messages"]
                company_context = state.get("company_context", {})
                system_message = build_system_message(company_context, system_prompt)
                messages_with_system = [SystemMessage(content=system_message)] + messages
                response = llm_with_tools.invoke(messages_with_system)
                return {"messages": [response]}

            agent_instance, _ = build_reaction_graph(agent, tools, model_gateway)

            # Execute action
            if action == "search_kols":
                return self._execute_search_kols_action(agent_instance, params, context)
            elif action == "generate_outreach":
                return self._execute_generate_outreach_action(agent_instance, params, context)
            elif action == "generate_performance_report":
                return self._execute_generate_performance_report_action(agent_instance, params, context)
            elif action == "generate_strategy_suggestion":
                return self._execute_generate_strategy_suggestion_action(agent_instance, params, context)
            else:
                return f"Unknown action: {action}"

        except Exception as e:
            logger.error(f"Error executing node {node['id']}: {e}")
            return f"Error: {e}"

    def _execute_search_kols_action(self, agent, params: dict, context: dict) -> str:
        """Execute search_kols action"""
        try:
            category = params.get("category", "beauty")
            count = params.get("count", 3)

            # Call agent's search_kols tool
            result = agent.search_kols(category, count)
            return f"Found {len(result.get('data', []))} KOLs in {category} category"

        except Exception as e:
            logger.error(f"Error in search_kols action: {e}")
            return f"Error: {e}"

    def _execute_generate_outreach_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_outreach action"""
        try:
            kol_name = params.get("kol_name", "")

            # Call agent's generate_outreach tool
            result = agent.generate_outreach(kol_name)
            return f"Generated outreach message for {kol_name}"

        except Exception as e:
            logger.error(f"Error in generate_outreach action: {e}")
            return f"Error: {e}"

    def _execute_generate_performance_report_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_performance_report action"""
        try:
            kol_name = params.get("kol_name", "")
            campaign_id = params.get("campaign_id", "")

            # Call agent's generate_performance_report tool
            result = agent.generate_performance_report(kol_name, campaign_id)
            return f"Generated performance report for {kol_name}"

        except Exception as e:
            logger.error(f"Error in generate_performance_report action: {e}")
            return f"Error: {e}"

    def _execute_generate_strategy_suggestion_action(self, agent, params: dict, context: dict) -> str:
        """Execute generate_strategy_suggestion action"""
        try:
            platform = params.get("platform", "xiaohongshu")
            category = params.get("category", "beauty")

            # Call agent's generate_strategy_suggestion tool
            _result = agent.generate_strategy_suggestion(platform, category)
            return f"Generated strategy suggestion for {platform} {category}"

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
            messages = db.get_pending_a2a_messages()
            workflow_messages = [msg for msg in messages if msg.get("task_description", "").startswith(f"Workflow {workflow.name}")]

            return {
                "workflow": {
                    "id": workflow.id,
                    "name": workflow.name,
                    "status": workflow.status,
                    "created_at": workflow.created_at.isoformat(),
                    "completed_at": workflow.completed_at.isoformat()
                },
                "messages": workflow_messages,
                "results": json.loads(workflow.result_json) if workflow.result_json else {}
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
            template_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'workflows', f'{template_name}.json')

            if not os.path.exists(template_path):
                raise FileNotFoundError(f"Workflow template not found: {template_path}")

            with open(template_path, encoding='utf-8') as f:
                template_data = json.load(f)

            logger.info(f"Loaded workflow template: {template_name}")
            return template_data

        except FileNotFoundError:
            raise FileNotFoundError(f"Workflow template '{template_name}' not found in config/workflows/")
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in workflow template '{template_name}': {e}")
        except Exception as e:
            raise Exception(f"Error loading workflow template '{template_name}': {e}")

    def _replace_template_variables(self, template_str: str, context: dict) -> str:
        """
        Replace template variables with context values
        
        Args:
            template_str: Template string with {{variable}} placeholders
            context: Dictionary of variable values
            
        Returns:
            String with variables replaced
        """
        try:
            result = template_str

            # Replace simple variables like {{category}}
            for key, value in context.items():
                placeholder = f'{{{{{key}}}}}'
                result = result.replace(placeholder, str(value))

            # Replace node result references like {{search_kols_node.result.name}}
            for key, value in context.items():
                if isinstance(value, dict):
                    # Handle nested dictionary references
                    for nested_key, nested_value in value.items():
                        placeholder = f'{{{{{key}.{nested_key}}}}}'
                        result = result.replace(placeholder, str(nested_value))

            return result

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
            template = self.load_workflow_template('brand_bd_workflow')

            # Convert template to JSON string for variable replacement
            template_json = json.dumps(template)

            # Replace template variables with context values
            definition_json = self._replace_template_variables(template_json, context)

            # Submit workflow to database
            workflow_id = db.create_workflow(company_id, template['name'], definition_json)

            # Parse and store workflow definition
            workflow_def = WorkflowDefinition(
                id=workflow_id,
                company_id=company_id,
                name=template['name'],
                definition_json=definition_json,
                status="pending"
            )

            self.current_workflows[workflow_id] = workflow_def
            logger.info(f"Brand BD workflow submitted: {template['name']} (ID: {workflow_id})")

            # Trigger workflow execution
            self._execute_workflow(workflow_def)

            return str(workflow_id)

        except Exception as e:
            logger.error(f"Error executing brand BD workflow: {e}")
            return f"Error executing brand BD workflow: {e}"
