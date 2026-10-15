#!/usr/bin/env python3
"""
Test script for Reddit Data Interface Adapter Manager.
This tests the functionality of the adapter manager and its integration.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from utils.reddit_api.adapter_manager import RedditAdapterManager
    from database.model_enums import PostDownloadSource
    
    print("Testing Reddit Data Interface Adapter Manager...")
    
    # Test singleton behavior
    manager1 = RedditAdapterManager()
    manager2 = RedditAdapterManager()
    
    if manager1 is manager2:
        print("✓ Singleton pattern works correctly")
    else:
        print("✗ Singleton pattern failed")
        sys.exit(1)
    
    # Test that we can import all adapters
    from utils.reddit_api.praw_adapter import PRAWAdapter
    from utils.reddit_api.arctic_shift_adapter import ArcticShiftAdapter
    from utils.reddit_api.pull_push_adapter import PullPushAdapter
    
    print("✓ All adapters imported successfully")
    
    # Test basic instantiation of manager
    manager = RedditAdapterManager()
    print("✓ Adapter Manager instantiated successfully")
    
    print("All tests passed!")
    
except Exception as e:
    print(f"Error during testing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)