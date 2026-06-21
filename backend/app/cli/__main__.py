"""
Agent Scaffold CLI - 入口
Usage:
    python -m app.cli create-agent <name> [--force]
    python -m app.cli decompose-task "<task_description>"
    python -m app.cli wizard
"""
import argparse
import sys

from app.cli.creator import create_agent
from app.cli.decomposer import decompose_task
from app.cli.wizard import run_wizard


def main():
    parser = argparse.ArgumentParser(
        description="AgentX Agent Scaffold CLI",
        prog="python -m app.cli",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # create-agent
    create_parser = subparsers.add_parser("create-agent", help="Create a new Agent from template")
    create_parser.add_argument("name", type=str, help="Agent name (e.g., customer_service)")
    create_parser.add_argument("--force", action="store_true", help="Overwrite existing agent")

    # decompose-task
    decompose_parser = subparsers.add_parser("decompose-task", help="Decompose a task into subtasks")
    decompose_parser.add_argument("task", type=str, help="Task description")

    # wizard
    wizard_parser = subparsers.add_parser("wizard", help="Interactive role assignment wizard")

    args = parser.parse_args()

    if args.command == "create-agent":
        result = create_agent(args.name, force=args.force)
        print(result)
    elif args.command == "decompose-task":
        result = decompose_task(args.task)
        print(result)
    elif args.command == "wizard":
        run_wizard()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()