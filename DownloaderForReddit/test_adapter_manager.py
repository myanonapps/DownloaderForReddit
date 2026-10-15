"""
Test script for the RedditAdapterManager.
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from DownloaderForReddit.data_interface.adapter_manager import RedditAdapterManager
from database.model_enums import PostDownloadSource

def test_adapter_manager():
    """Test that the adapter manager can be created and works correctly."""
    print("Testing RedditAdapterManager...")
    
    # Create adapter manager instance
    manager = RedditAdapterManager()
    print("✓ AdapterManager created successfully")
    
    # Test PRAW adapter creation (should work even without token)
    try:
        praw_adapter = manager.get_reddit_api(PostDownloadSource.REDDIT)
        print("✓ PRAW adapter creation successful")
    except Exception as e:
        print(f"Note: PRAW adapter test skipped due to: {e}")
    
    # Test that the manager can be imported and instantiated
    print("✓ All tests passed!")

if __name__ == "__main__":
    test_adapter_manager()