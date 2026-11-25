"""
Recognizes Reddit chat reactions and keeps the library of reaction images that every chat shares.

Reddit's export records a chat reaction as a chat message whose whole text is the url of one of Reddit's reaction
images (GIF or PNG), replying to the message reacted to.  Images people upload to a chat are served from Reddit's chat media store
(matrix.redditspace.com), never from i.redd.it, and a link shared in a sentence is not the whole text of its message,
so a message is taken for a reaction when all of these hold:

- its whole text is a single i.redd.it GIF or PNG url,
- it replies to another message (the message it reacts to),
- the user has not marked that url as not being a reaction.

Each distinct url is stored once as a ChatReaction.  The user can also mark any single image url as a reaction, which
then applies to every message that is only that url, in every chat, reply or not.


Copyright (C) 2017, Kyle Hickey


This file is part of the Downloader for Reddit.

Downloader for Reddit is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Downloader for Reddit is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Downloader for Reddit.  If not, see <http://www.gnu.org/licenses/>.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database.export_models import ChatMessage, ChatReaction


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

REACTION_URL = re.compile(r'^https?://i\.redd\.it/[a-z0-9]+\.(gif|png)$', re.IGNORECASE)
_SINGLE_URL = re.compile(r'^https?://\S+$', re.IGNORECASE)
_ID_QUERY_SIZE = 500  # stays below SQLite's bound parameter limit


@dataclass
class ReactionUsage:  # pylint: disable=too-many-instance-attributes  # plain record of one row of the reactions dialog
    """How often a reaction was used: by how many messages, in how many chats, and when it was first and last used."""

    reaction_id: int
    url: str
    name: Optional[str]
    display_name: str
    enabled: bool
    image_path: Optional[str]
    uses: int
    chats: int
    first_used: Optional[datetime]
    last_used: Optional[datetime]


def single_url(body: Optional[str]) -> Optional[str]:
    """
    Returns the url a message consists of, when its whole text is one url.
    :param body: The message text.
    :type body: Optional[str]
    :return: The url, or None when the text is empty, holds anything besides the url, or holds several urls.
    :rtype: Optional[str]
    """
    text = (body or '').strip()
    return text if _SINGLE_URL.match(text) else None


def reaction_url(body: Optional[str]) -> Optional[str]:
    """
    Returns the reaction image url a message consists of, when its whole text is one i.redd.it GIF or PNG url.
    :param body: The message text.
    :type body: Optional[str]
    :return: The url, or None when the text is anything else.
    :rtype: Optional[str]
    """
    url = single_url(body)
    return url if url is not None and REACTION_URL.match(url) else None


def _known_reactions(session: Session) -> dict[str, ChatReaction]:
    """
    Returns every stored reaction, keyed by its url in lower case.
    :param session: The database session.
    :type session: Session
    :return: The reactions.
    :rtype: dict[str, ChatReaction]
    """
    return {reaction.url.lower(): reaction for reaction in session.query(ChatReaction) if reaction.url}


def _unlinked_messages(session: Session, message_ids: Optional[Iterable[int]]) -> Iterable[ChatMessage]:
    """
    Yields the chat messages not linked to a reaction whose text starts like a url.
    :param session: The database session.
    :type session: Session
    :param message_ids: The database ids of the messages to look at, or None for every message.
    :type message_ids: Optional[Iterable[int]]
    :return: The messages.
    :rtype: Iterable[ChatMessage]
    """
    query = session.query(ChatMessage).filter(ChatMessage.reaction_id.is_(None), func.ltrim(ChatMessage.body).like('http%'))
    if message_ids is None:
        yield from query.all()
        return
    ids = list(message_ids)
    for start in range(0, len(ids), _ID_QUERY_SIZE):
        yield from query.filter(ChatMessage.id.in_(ids[start:start + _ID_QUERY_SIZE])).all()


def link_chat_reactions(session: Session, message_ids: Optional[Iterable[int]] = None) -> int:
    """
    Links chat messages that are reactions to their reaction, creating a reaction for each new url.  A message whose
    url is already a stored reaction is linked to it whether or not it is a reply; otherwise the message must be a
    reply whose url is a reaction image.  Messages linked to an enabled reaction are marked extracted, so their image
    is not downloaded again for each message.  Running it again links nothing new.
    :param session: The database session; the caller commits.
    :type session: Session
    :param message_ids: The database ids of the messages to look at, or None for every chat message.
    :type message_ids: Optional[Iterable[int]]
    :return: The number of messages linked.
    :rtype: int
    """
    known = _known_reactions(session)
    linked = 0
    for message in _unlinked_messages(session, message_ids):
        url = single_url(message.body)
        if url is None:
            continue
        reaction = known.get(url.lower())
        if reaction is None:
            if not message.thread_parent_message_id or not REACTION_URL.match(url):
                continue
            reaction = ChatReaction(url=url, enabled=True)
            session.add(reaction)
            known[url.lower()] = reaction
        message.reaction = reaction
        if reaction.enabled:
            message.extracted = True
        linked += 1
    if linked:
        logger.info('Linked %d chat messages to reactions', linked)
    return linked


def set_reaction_enabled(session: Session, url: str, enabled: bool) -> ChatReaction:
    """
    Marks an image url as a reaction, or as not being one, in every chat.  Marking it a reaction links every chat
    message whose whole text is that url and marks them extracted.  Marking it not a reaction keeps the reaction (so
    the url is not recognized again) and lets the media of its messages that have none yet be downloaded.
    :param session: The database session; the change is committed.
    :type session: Session
    :param url: The image url.
    :type url: str
    :param enabled: True to treat the url as a reaction, False to treat it as ordinary media.
    :type enabled: bool
    :return: The reaction.
    :rtype: ChatReaction
    """
    url = url.strip()
    reaction = session.query(ChatReaction).filter(ChatReaction.url == url).first()
    if reaction is None:
        reaction = ChatReaction(url=url)
        session.add(reaction)
    reaction.enabled = enabled
    if enabled:
        matching = session.query(ChatMessage).filter(func.lower(func.trim(ChatMessage.body)) == url.lower())
        for message in matching:
            message.reaction = reaction
            message.extracted = True
    else:
        for message in reaction.messages:
            if not message.content:
                message.extracted = False
    session.commit()
    logger.info('Marked %s as %s', url, 'a reaction' if enabled else 'not a reaction')
    return reaction


def rename_reaction(session: Session, reaction_id: int, name: str) -> Optional[ChatReaction]:
    """
    Gives a reaction a name of the user's own, or clears it when the name is blank, and commits.
    :param session: The database session.
    :type session: Session
    :param reaction_id: The reaction's database id.
    :type reaction_id: int
    :param name: The new name.
    :type name: str
    :return: The reaction, or None when no reaction has the id.
    :rtype: Optional[ChatReaction]
    """
    reaction = session.query(ChatReaction).get(reaction_id)
    if reaction is None:
        return None
    reaction.name = name.strip() or None
    session.commit()
    return reaction


def reaction_usage(session: Session) -> list[ReactionUsage]:
    """
    Describes every stored reaction and how it was used, the most used first.
    :param session: The database session.
    :type session: Session
    :return: One record per reaction.
    :rtype: list[ReactionUsage]
    """
    stats = {reaction_id: (uses, chats, first, last) for reaction_id, uses, chats, first, last in
             session.query(ChatMessage.reaction_id, func.count(ChatMessage.id), func.count(func.distinct(ChatMessage.channel_id)),
                           func.min(ChatMessage.date_posted), func.max(ChatMessage.date_posted))
             .filter(ChatMessage.reaction_id.isnot(None)).group_by(ChatMessage.reaction_id)}
    usage = []
    for reaction in session.query(ChatReaction).order_by(ChatReaction.id):
        uses, chats, first, last = stats.get(reaction.id, (0, 0, None, None))
        usage.append(ReactionUsage(reaction.id, reaction.url, reaction.name, reaction.display_name, bool(reaction.enabled),
                                   reaction.file_path if reaction.has_image else None, uses, chats, first, last))
    usage.sort(key=lambda record: -record.uses)
    return usage
