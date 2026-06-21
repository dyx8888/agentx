#!/usr/bin/env python3
"""Debug script to test agent loading"""

import os
import sys

# Add backend to path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

try:
    from app.agent import get_agent_by_name
    print("✅ Successfully imported get_agent_by_name")

    # Test the function
    result = get_agent_by_name("brand_bd")
    print(f"✅ Function returned: {type(result)}")
    print(f"✅ Result length: {len(result) if hasattr(result, '__len__') else 'N/A'}")

    if result is None:
        print("❌ Function returned None")
    elif isinstance(result, tuple) and len(result) == 2:
        system_prompt, tools = result
        print(f"✅ System prompt type: {type(system_prompt)}")
        print(f"✅ Tools type: {type(tools)}")
        print(f"✅ Tools count: {len(tools) if hasattr(tools, '__len__') else 'N/A'}")
    else:
        print(f"❌ Unexpected result format: {result}")

except Exception as e:
    print(f"❌ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
