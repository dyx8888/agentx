#!/usr/bin/env python3
"""Debug script to test chat agent loading"""

import os
import sys

# Add backend to path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

try:
    print("Testing import and function call...")

    # Test the import
    from app.agent import get_agent_by_name, get_agent_for_tools
    print("✅ Successfully imported functions")

    # Test the function call
    result = get_agent_by_name("brand_bd")
    print(f"✅ Function returned: {type(result)}")

    if result is None:
        print("❌ Function returned None")
    elif isinstance(result, tuple) and len(result) == 2:
        system_prompt, default_tools = result
        print(f"✅ System prompt type: {type(system_prompt)}")
        print(f"✅ Default tools type: {type(default_tools)}")
        print(f"✅ Tools count: {len(default_tools) if hasattr(default_tools, '__len__') else 'N/A'}")

        # Test get_agent_for_tools
        try:
            agent_app, model_gateway = get_agent_for_tools(default_tools, system_prompt)
            print("✅ get_agent_for_tools succeeded")
        except Exception as e:
            print(f"❌ get_agent_for_tools failed: {type(e).__name__}: {e}")
    else:
        print(f"❌ Unexpected result format: {result}")

except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
