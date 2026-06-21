#!/usr/bin/env python3
"""Debug script to test tool loading"""

import os
import sys

# Add backend to path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

try:
    from app.tools.registry import registry

    # Initialize registry
    print("Initializing ToolRegistry...")
    registry.initialize_from_config()

    # Test getting tools for brand_bd agent
    tool_names = [
        "search_kols", "generate_outreach", "generate_script",
        "check_delivery_status", "generate_arrival_script",
        "generate_performance_report", "generate_strategy_suggestion",
        "delegate_task", "a2a_delegate_task"
    ]

    print(f"Getting tools for: {tool_names}")
    tools = registry.get_tools_by_names(tool_names)

    print(f"✅ Retrieved {len(tools)} tools")
    for i, tool in enumerate(tools):
        print(f"  Tool {i}: {type(tool)} - {getattr(tool, 'name', 'No name')}")
        if hasattr(tool, 'name'):
            print(f"    Name: {tool.name}")
        if hasattr(tool, 'description'):
            print(f"    Description: {tool.description[:100]}...")

    # Test for duplicates
    tool_names_set = set()
    for tool in tools:
        tool_name = getattr(tool, 'name', str(tool))
        if tool_name in tool_names_set:
            print(f"❌ Duplicate tool found: {tool_name}")
        else:
            tool_names_set.add(tool_name)

    print(f"✅ Unique tool count: {len(tool_names_set)}")

except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
