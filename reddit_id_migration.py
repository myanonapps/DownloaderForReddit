import logging
from sqlalchemy import func

from DownloaderForReddit.data_interface.name_checker import NameChecker
from DownloaderForReddit.database.models import Subreddit, User
from DownloaderForReddit.utils import injector

logger = logging.getLogger('DownloaderForReddit.Migration')


def migrate_reddit_ids():
    """
    Migrates existing User and Subreddit records to populate reddit_id values.
    This script should be run after the database schema has been updated with 
    reddit_id columns for User and Subreddit tables.
    """
    logger.info("Starting reddit_id migration for existing records")
    
    db = injector.get_database_handler()
    settings_manager = injector.get_settings_manager()
    
    # Process Users
    logger.info("Processing User records...")
    with db.get_scoped_session() as session:
        # Find users without reddit_id
        users_without_id = session.query(User).filter(
            func.coalesce(User.reddit_id, '') == ''
        ).all()
        
        processed_users = 0
        for user in users_without_id:
            try:
                # Get the Reddit ID by validating the username
                # Use USER source for User objects
                name_checker = NameChecker(user.post_download_source, 'USER')
                validation_set = name_checker.check_user_name(user.name)
                
                if validation_set.valid:
                    user.reddit_id = validation_set.reddit_id
                    processed_users += 1
                    
                    if processed_users % 100 == 0:  # Log every 100 records
                        logger.info(f"Processed {processed_users} users")
                        
            except Exception as e:
                logger.warning(f"Failed to process user '{user.name}': {str(e)}")
                continue
        
        try:
            session.commit()
            logger.info(f"Successfully updated reddit_id for {processed_users} users")
        except Exception as e:
            logger.error(f"Error committing user updates: {str(e)}")
            session.rollback()

    # Process Subreddits
    logger.info("Processing Subreddit records...")
    with db.get_scoped_session() as session:
        # Find subreddits without reddit_id
        subreddits_without_id = session.query(Subreddit).filter(
            func.coalesce(Subreddit.reddit_id, '') == ''
        ).all()
        
        processed_subreddits = 0
        for subreddit in subreddits_without_id:
            try:
                # Get the Reddit ID by validating the subreddit name
                # Use SUBREDDIT source for Subreddit objects
                name_checker = NameChecker(subreddit.post_download_source, 'SUBREDDIT')
                validation_set = name_checker.check_subreddit_name(subreddit.name)
                
                if validation_set.valid:
                    subreddit.reddit_id = validation_set.reddit_id
                    processed_subreddits += 1
                    
                    if processed_subreddits % 100 == 0:  # Log every 100 records
                        logger.info(f"Processed {processed_subreddits} subreddits")
                        
            except Exception as e:
                logger.warning(f"Failed to process subreddit '{subreddit.name}': {str(e)}")
                continue
        
        try:
            session.commit()
            logger.info(f"Successfully updated reddit_id for {processed_subreddits} subreddits")
        except Exception as e:
            logger.error(f"Error committing subreddit updates: {str(e)}")
            session.rollback()

    logger.info("Reddit_id migration completed")


migrate_reddit_ids()