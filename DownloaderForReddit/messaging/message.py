from enum import Enum, StrEnum
from typing import Optional
from datetime import datetime, timezone

from ..utils import injector

class ContentOutput(StrEnum):
    FULL_PATH = "Full path"
    USER_TITLE = "User name & title"

class MessageType(Enum):

    TEXT = 1

    POTENTIAL_PROGRESS = 2
    ACTUAL_PROGRESS = 3
    POTENTIAL_COUNT = 4
    ACTUAL_COUNT = 5

    STATUS_TRAY = 6

    FINISHED_STATS = 7


class MessagePriority(Enum):

    DEBUG = 1
    INFO = 2
    WARNING = 3
    ERROR = 4
    CRITICAL = 5
    REQUESTED = 10


class Message:

    message_queue = injector.get_message_queue()

    def __init__(self, message_type: MessageType, message: Optional[str] = None,
                 priority: MessagePriority = MessagePriority.INFO, session_id:int = 0):
        self.message_type = message_type
        self.message = message
        self.priority = priority
        self.session_id = session_id
        self.datetime = datetime.now(timezone.utc)

    def to_string(self, settings_manager):
        datetime_string = ""
        sessionid_string = ""
        priority_string = ""
        if settings_manager.show_priority_level:
            priority_string = f"{self.priority.name} "
        if settings_manager.show_datetime:
            try:
                if settings_manager.datetime_format:
                    datetime_string = f'[{self.datetime.astimezone().strftime(settings_manager.datetime_format)}] '
                else:
                    datetime_string = f'[{self.datetime.astimezone().strftime("%m/%d/%y %I:%M:%S %p")}] '
            except Exception:
                datetime_string = f'[{self.datetime.astimezone().strftime("%m/%d/%y %I:%M:%S %p")}] '
        if settings_manager.show_session_id and self.session_id:
            sessionid_string = f"({self.session_id}) "
        prefix = f'{datetime_string}{sessionid_string}{priority_string}'
        if prefix:
            return f'{prefix}:  {self.message}'
        return f'{self.message}'

    @classmethod
    def send(cls, message_type: MessageType, message: Optional[str] = None,
             priority: MessagePriority = MessagePriority.INFO, session_id:int = 0) -> None:
        m = cls(message_type, message, priority, session_id=session_id)
        cls.message_queue.put(m)

    @classmethod
    def send_debug(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.DEBUG, session_id=session_id)

    @classmethod
    def send_info(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.INFO, session_id=session_id)

    @classmethod
    def send_warning(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.WARNING, session_id=session_id)

    @classmethod
    def send_error(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.ERROR, session_id=session_id)

    @classmethod
    def send_critical(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.CRITICAL, session_id=session_id)

    @classmethod
    def send_requested(cls, message: str, session_id:int = 0) -> None:
        cls.send(MessageType.TEXT, message, MessagePriority.REQUESTED, session_id=session_id)

    @classmethod
    def send_extraction_error(cls, message: str, session_id:int = 0):
        cls.send(MessageType.POTENTIAL_PROGRESS, priority=MessagePriority.ERROR, session_id=session_id)
        cls.send(MessageType.TEXT, message, MessagePriority.ERROR, session_id=session_id)

    @classmethod
    def send_finished_stats(cls, message_json: str, session_id:int = 0):
        cls.send(MessageType.FINISHED_STATS, message_json, MessagePriority.INFO, session_id=session_id)

    @classmethod
    def send_download_error(cls, message: str, session_id:int = 0):
        cls.send(MessageType.POTENTIAL_PROGRESS, priority=MessagePriority.ERROR, session_id=session_id)
        cls.send(MessageType.TEXT, message, MessagePriority.ERROR, session_id=session_id)

    @classmethod
    def send_status_tray(cls, message: str, session_id:int = 0):
        cls.send(MessageType.STATUS_TRAY, message, priority=MessagePriority.INFO, session_id=session_id)
