import os
import sys
import uuid

import structlog
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.core.logging import get_logger

logger = get_logger(__name__)

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

def main():
    """Main CLI function using the centralized agent"""
    cli_request_id = f"cli-{uuid.uuid4().hex[:12]}"
    structlog.contextvars.bind_contextvars(
        request_id=cli_request_id,
        channel="cli",
    )
    try:
        # Import the agent module
        from app.agent import build_reaction_graph, build_system_message, State
        from app.services.model_gateway import get_global_model_gateway
        from app.tools.registry import registry

        # Get agent instance
        model_gateway = get_global_model_gateway()
        llm = model_gateway.get_llm()
        tool_names = registry.list_registered_tools()
        tools = registry.get_tools_by_names(tool_names)
        llm_with_tools = llm.bind_tools(tools)

        def agent(state: State):
            messages = state["messages"]
            company_context = state.get("company_context", {})
            system_message = build_system_message(company_context)
            messages_with_system = [SystemMessage(content=system_message)] + messages
            response = llm_with_tools.invoke(messages_with_system)
            return {"messages": [response]}

        app, model_gateway = build_reaction_graph(agent, tools, model_gateway)

        print(f"Using model: {model_gateway.get_default_model()}")
        print("LangGraph Agent with KOL Marketing Tools")
        print("Type 'quit' to exit")
        print("-" * 40)

        # Initialize conversation state
        state = {"messages": []}

        while True:
            user_input = input("You: ").strip()

            if user_input.lower() in ['quit', 'exit', 'q']:
                print("Goodbye!")
                break

            if not user_input:
                continue

            # Add user message to state
            state["messages"].append(HumanMessage(content=user_input))

            # Run the agent with current state
            try:
                updated_state = app.invoke(state)

                # Update state with new messages
                state = updated_state

                # Get the last AI message
                ai_message = state["messages"][-1]
                if isinstance(ai_message, AIMessage):
                    print(f"Agent: {ai_message.content}")
                else:
                    print(f"Agent: {ai_message}")

            except Exception as e:
                logger.error("cli_agent_error", error=str(e))

            print()

    except Exception as e:
        logger.error("cli_agent_init_error", error=str(e))
        print("Please check your model configuration and environment variables")
        sys.exit(1)
    finally:
        structlog.contextvars.clear_contextvars()

def run_feedback_api():
    """Run the feedback API server"""
    import uvicorn
    from fastapi import FastAPI

    from app.api.feedback import router as feedback_router

    # Create FastAPI app for standalone feedback server
    app = FastAPI(title="Feedback API", version="1.0.0")
    app.include_router(feedback_router, prefix="/feedback")

    uvicorn.run(app, host="0.0.0.0", port=8001)

if __name__ == "__main__":
    import sys

    # Check if user wants to run CLI or API server
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        logger.info("feedback_api_starting", port=8001)
        run_feedback_api()
    else:
        logger.info("cli_agent_starting")
        main()
