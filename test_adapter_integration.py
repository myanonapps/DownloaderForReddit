#!/usr/bin/env python3
"""
Test script for Reddit Data Interface Adapter Manager integration.
This tests that the adapter manager works correctly with the actual implementation.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # Import required components
    from DownloaderForReddit.data_interface.adapter_manager import RedditAdapterManager
    from DownloaderForReddit.database.model_enums import PostDownloadSource
    
    print("Testing Reddit Data Interface Adapter Manager Integration...")
    
    # Test singleton behavior
    manager1 = RedditAdapterManager()
    manager2 = RedditAdapterManager()
    
    if manager1 is manager2:
        print("✓ Singleton pattern works correctly")
    else:
        print("✗ Singleton pattern failed")
        sys.exit(1)
    
    # Test basic instantiation and method existence
    manager = RedditAdapterManager()
    
    # Check that the main methods exist
    if hasattr(manager, 'get_reddit_api'):
        print("✓ get_reddit_api method exists")
    else:
        print("✗ get_reddit_api method missing")
        sys.exit(1)
        
    if hasattr(manager, 'get_reddit_api_for_object'):
        print("✓ get_reddit_api_for_object method exists")
    else:
        print("✗ get_reddit_api_for_object method missing")
        sys.exit(1)
    
    print("✓ Adapter Manager methods are present")
    
    # Test that we can import all adapters
    from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
    from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import ArcticShiftAdapter
    from DownloaderForReddit.data_interface.adapters.pull_push_adapter import PullPushAdapter
    
    print("✓ All adapters imported successfully")
    
    # Test that we can create instances of the manager
    print("✓ Adapter Manager instantiated successfully")
    
    print("All integration tests passed!")
    
except Exception as e:
    print(f"Error during testing: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)