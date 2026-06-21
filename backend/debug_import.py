#!/usr/bin/env python3
"""Debug script to test the exact import pattern used in chat.py"""

import os
import sys

# Add backend to path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

try:
    print("Testing the exact import pattern from chat.py...")

    # Test the exact import pattern
    agent_module = __import__('app.agent', fromlist=['get_agent_by_name', 'get_agent_for_tools'])
    print(f"✅ Imported module: {type(agent_module)}")

    if agent_module is None:
        print("❌ Module is None")
    else:
        print(f"✅ Module attributes: {dir(agent_module)}")

        # Test getting the functions
        get_agent_by_name = getattr(agent_module, 'get_agent_by_name', None)
        get_agent_for_tools = getattr(agent_module, 'get_agent_for_tools', None)

        print(f"✅ get_agent_by_name: {type(get_agent_by_name)}")
        print(f"✅ get_agent_for_tools: {type(get_agent_for_tools)}")

        if get_agent_by_name is None:
            print("❌ get_agent_by_name is None")
        else:
            # Test calling the function
            result = get_agent_by_name("brand_bd")
            print(f"✅ Function call result: {type(result)}")

except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
