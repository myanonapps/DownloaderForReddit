"""
Unit tests for Reddit Data Interface interface and adapters.
"""

import unittest
from unittest.mock import Mock, patch

# Import our modules
from DownloaderForReddit.data_interface.reddit_data_interface import RedditDataInterface
from DownloaderForReddit.data_interface.adapters.praw_adapter import PRAWAdapter
from DownloaderForReddit.data_interface.adapters.arctic_shift_adapter import ArcticShiftAdapter
from DownloaderForReddit.data_interface.adapters.pull_push_adapter import PullPushAdapter


class TestRedditDataInterface(unittest.TestCase):
    """Test the abstract RedditAPI base class."""
    
    def test_abstract_base_class(self):
        """Test that RedditAPI is an abstract base class."""
        # Should not be able to instantiate directly
        with self.assertRaises(TypeError):
            RedditDataInterface()


class TestPRAWAdapter(unittest.TestCase):
    """Test the PRAWAdapter implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.adapter = PRAWAdapter()
    
    def test_initialization(self):
        """Test adapter initialization."""
        self.assertIsInstance(self.adapter, RedditDataInterface)
        self.assertFalse(self.adapter.is_authenticated())
        
    @patch('praw.Reddit')
    def test_submission(self, mock_reddit):
        """Test submission method."""
        mock_submission = Mock()
        mock_reddit.return_value.submission.return_value = mock_submission
        result = self.adapter.submission("test_id")
        self.assertEqual(result, mock_submission)
        
    @patch('praw.Reddit')
    def test_redditor(self, mock_reddit):
        """Test redditor method."""
        mock_redditor = Mock()
        mock_reddit.return_value.redditor.return_value = mock_redditor
        result = self.adapter.redditor("test_user")
        self.assertEqual(result, mock_redditor)
        
    @patch('praw.Reddit')
    def test_subreddit(self, mock_reddit):
        """Test subreddit method."""
        mock_subreddit = Mock()
        mock_reddit.return_value.subreddit.return_value = mock_subreddit
        result = self.adapter.subreddit("test_sub")
        self.assertEqual(result, mock_subreddit)
        
    def test_is_authenticated(self):
        """Test authentication check."""
        self.assertFalse(self.adapter.is_authenticated())
        
    def test_get_user_agent(self):
        """Test user agent retrieval."""
        user_agent = self.adapter.get_user_agent()
        self.assertIsInstance(user_agent, str)
        self.assertTrue(len(user_agent) > 0)


class TestArcticShiftAdapter(unittest.TestCase):
    """Test the ArcticShiftAdapter implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.api_key = "test_api_key"
        self.adapter = ArcticShiftAdapter(self.api_key)
    
    def test_initialization(self):
        """Test adapter initialization."""
        self.assertIsInstance(self.adapter, RedditDataInterface)
        self.assertEqual(self.adapter.api_key, self.api_key)
        
    @patch('requests.Session')
    def test_make_request(self, mock_session):
        """Test internal request method."""
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        mock_session.return_value.get.return_value = mock_response
        
        result = self.adapter._make_request("/test-endpoint")
        self.assertEqual(result, {"test": "data"})
        
    def test_is_authenticated(self):
        """Test authentication check."""
        self.assertTrue(self.adapter.is_authenticated())
        
    def test_get_user_agent(self):
        """Test user agent retrieval."""
        user_agent = self.adapter.get_user_agent()
        self.assertIsInstance(user_agent, str)
        self.assertTrue(len(user_agent) > 0)


class TestPullPushAdapter(unittest.TestCase):
    """Test the PullPushAdapter implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.api_key = "test_api_key"
        self.adapter = PullPushAdapter(self.api_key)
    
    def test_initialization(self):
        """Test adapter initialization."""
        self.assertIsInstance(self.adapter, RedditDataInterface)
        self.assertEqual(self.adapter.api_key, self.api_key)
        
    @patch('requests.Session')
    def test_make_request(self, mock_session):
        """Test internal request method."""
        mock_response = Mock()
        mock_response.json.return_value = {"test": "data"}
        mock_response.raise_for_status.return_value = None
        mock_session.return_value.get.return_value = mock_response
        
        result = self.adapter._make_request("/test-endpoint")
        self.assertEqual(result, {"test": "data"})
        
    def test_is_authenticated(self):
        """Test authentication check."""
        self.assertTrue(self.adapter.is_authenticated())
        
    def test_get_user_agent(self):
        """Test user agent retrieval."""
        user_agent = self.adapter.get_user_agent()
        self.assertIsInstance(user_agent, str)
        self.assertTrue(len(user_agent) > 0)


if __name__ == '__main__':
    unittest.main()