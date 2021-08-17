# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause

import asyncio
import secrets
import base64
from dataclasses import dataclass
from typing import Optional

from quart import request


@dataclass
class Session:
    user_id: str
    queue: asyncio.Queue


@dataclass
class IncomingRequest:
    session_id: str
    path: str
    headers: dict
    body: str
    response_event: asyncio.Event
    response: Optional[dict] = None


class SessionManager:
    """Hold mappings from asot subdomains to websocket connections"""

    def __init__(self):
        self.user_to_session = {}
        self.sessions = {}
        self.requests = {}

    def add_with_session_id(self, user_id, session_id):
        session = Session(user_id=user_id, queue=asyncio.Queue())
        self.sessions[session_id] = session
        self.user_to_session[user_id] = session_id
        return session_id

    def add_client(self, user_id):
        return self.add_with_session_id(user_id, secrets.token_hex(6))

    def get_by_user(self, user_id: str):
        return self.sessions[self.user_to_session[user_id]]

    def get_by_id(self, session_id: str):
        return self.sessions.get(session_id)

    async def send_request(self, session_id) -> asyncio.Event:
        sess = self.get_by_id(session_id)
        assert sess is not None

        request_id = secrets.token_hex(32)
        response_event = asyncio.Event()
        body: str = base64.b64encode(await request.get_data()).decode()
        self.requests[request_id] = IncomingRequest(
            session_id,
            request.path,
            dict(request.headers),
            body,
            response_event,
            None,
        )

        # notify client we have a new request for it
        await sess.queue.put(
            (
                1,
                request_id,
            )
        )
        return request_id

    def delete_session(self, session_id):
        sess = self.sessions.pop(session_id)
        mapped_session = self.user_to_session[sess.user_id]

        # prevent race conditions by only deleting our own
        # session data. if a new session overwrote user_to_session
        # we MUST NOT interfere with it
        if mapped_session == session_id:
            self.user_to_session.pop(user_id)
