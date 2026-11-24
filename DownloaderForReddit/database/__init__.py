from sqlalchemy import event

from ..scheduling.tasks import DownloadTask  # import here so the database table is created along with the others
from .models import Post, Content, Comment
from . import export_models  # import here so the export import tables are created with the others
from ..messaging.message import Message, MessageType


@event.listens_for(Post, 'after_insert')
def post_created(mapper, connection, target):
    Message.send(MessageType.POTENTIAL_PROGRESS)


@event.listens_for(Post.extracted, 'set')
def post_extracted(target, value, oldValue, initiator):
    if value:
        Message.send(MessageType.ACTUAL_PROGRESS)


class UnlinkedContentError(ValueError):
    """Raised when content is stored without the post, comment or imported message it was found in."""


def has_source(content: Content) -> bool:
    """
    Whether content is tied to where it was found: a post, a comment, or an imported chat or private message.
    :param content: The content.
    :type content: Content
    :return: True when the content has a source.
    :rtype: bool
    """
    return any(value is not None for value in (content.post_id, content.post, content.comment_id, content.comment,
                                               content.chat_message_id, content.chat_message,
                                               content.private_message_id, content.private_message))


@event.listens_for(Content, 'before_insert')
def require_content_source(_mapper: object, _connection: object, target: Content) -> None:
    """
    Refuses to store content that is not tied to a post, comment or message.  Message content in particular has no
    post, so this keeps it from being stored without its message.
    :param _mapper: The Content mapper (unused; part of the event signature).
    :type _mapper: object
    :param _connection: The connection the insert runs on (unused; part of the event signature).
    :type _connection: object
    :param target: The content being inserted.
    :type target: Content
    :return: None
    :rtype: None
    :raises UnlinkedContentError: When the content has no source.
    """
    if not has_source(target):
        raise UnlinkedContentError(f'Content {target.url!r} is not tied to a post, comment or message')


@event.listens_for(Content, 'after_insert')
def content_created(mapper, connection, target):
    Message.send(MessageType.POTENTIAL_COUNT)


@event.listens_for(Content.downloaded, 'set')
def content_downloaded(target, value, oldValue, initiator):
    if value:
        Message.send(MessageType.ACTUAL_COUNT)


@event.listens_for(Comment, 'after_insert')
def comment_created(mapper, connection, target):
    Message.send(MessageType.POTENTIAL_PROGRESS)


@event.listens_for(Comment.extracted, 'set')
def comment_extracted(target, value, oldValue, initiator):
    if value:
        Message.send(MessageType.ACTUAL_PROGRESS)
