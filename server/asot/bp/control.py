# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause

import json
import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from quart import Blueprint, websocket, current_app as app, g
import violet.fail_modes

from asot.models import User

bp = Blueprint("control", __name__)
log = logging.getLogger(__name__)


class CloseCodes:
    ERROR = 4000
    FAILED_AUTH = 4001
    HEARTBEAT_EXPIRE = 4002
    INVALID_JSON = 4003
    INVALID_MESSAGE = 4004


class OperationType(Enum):
    LOGIN = 1
    WELCOME = 2
    HEARTBEAT = 3
    HEARTBEAT_ACK = 4
    HTTP_REQUEST = 5
    HTTP_RESPONSE = 6
    RESUME = 7


async def execute_and_commit(db, stmt, args):
    async with db.execute(stmt, args) as cur:
        await db.commit()


async def receive_any():
    data_str = await websocket.receive()
    log.debug("got message: %r", data_str)
    try:
        data = json.loads(data_str)
        return data
    except json.JSONDecodeError:
        raise WebsocketClose(CloseCodes.INVALID_JSON, "Invalid JSON")


async def recv_any_op():
    message = await receive_any()
    if "op" not in message:
        raise WebsocketClose(
            CloseCodes.INVALID_MESSAGE, "Invalid Message (no op field)"
        )

    if "d" not in message:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Invalid Message (no d field)")
    return message


async def recv_op(op: OperationType):
    data = await recv_any_op()

    if data["op"] != op.value:
        raise WebsocketClose(
            CloseCodes.INVALID_MESSAGE,
            f"Invalid Message (expected op {op.value!r}, got {data['op']})",
        )

    return data["d"]


async def send_op(op: OperationType, data: dict):
    message = {"op": op.value, "d": data}
    log.debug("sending: %r", message)
    await websocket.send(json.dumps(message))


@dataclass
class WebsocketClose(Exception):
    code: int
    reason: str


class WebsocketFailMode(violet.fail_modes.FailMode):
    """Failure mode that behaves to RaiseErr() but not when WebsocketClose is raised."""

    def __init__(self):
        pass

    async def handle(self, job, exc, state) -> bool:
        if isinstance(exc, WebsocketClose):
            raise exc
        else:
            await violet.fail_modes.LogOnly().handle(job, exc, state)


async def register_session(session_id, user_id):
    await execute_and_commit(
        app.db,
        """
        INSERT INTO asot_sessions
            (user_id, session_id, created_at)
        VALUES
            (?, ?, ?)
        """,
        (user_id, session_id, datetime.utcnow().isoformat()),
    )


async def fetch_session_id(user_id):
    async with app.db.execute(
        """
        SELECT session_id, created_at FROM asot_sessions
        WHERE user_id = ?
        """,
        (user_id,),
    ) as cursor:
        row = await cursor.fetchone()

    # if we don't find a pre-existing session for the given user, create
    # a new one, register it on db
    if row is None:
        session_id = app.sessions.add_client(user_id)
        await register_session(session_id, user_id)
        return session_id

    # else, attempt to restore it from the db into memory
    # but only if the session is younger than 8 hours.
    existing_session_id, created_at_str = row
    created_at = datetime.fromisoformat(created_at_str)
    now = datetime.utcnow()
    delta = now - created_at
    if delta.total_seconds() > (8 * 3600):
        # if a session is older than 8h, destroy it in the db and create
        # a new one, register it on db
        await execute_and_commit(
            app.db,
            """
            DELETE FROM asot_sessions
            WHERE user_id = ?
            """,
            (user_id,),
        )

        app.sessions.delete_session(existing_session_id)

        # create new session
        session_id = app.sessions.add_client(user_id)
        log.info("created session %r", session_id)

        return session_id
    else:
        # session is young, just reuse session
        return app.sessions.add_with_session_id(user_id, existing_session_id)


async def do_login():
    await websocket.accept()
    message = await recv_any_op()
    opcode = OperationType(message["op"])

    # can either be LOGIN or RESUME
    if opcode == OperationType.LOGIN:
        login = message["d"]
        user_id = login["user_id"]

        user = await User.fetch(user_id)
        if user is None:
            raise WebsocketClose(CloseCodes.FAILED_AUTH, "unknown user")

        session_id = await fetch_session_id(user_id)
        g.state = WebsocketConnectionState(user, session_id, None)
        await send_op(OperationType.WELCOME, {"session_id": session_id})
    elif opcode == OperationType.RESUME:
        # TODO
        raise NotImplementedError()
    else:
        raise WebsocketClose(
            CloseCodes.INVALID_MESSAGE,
            "Unexpected opcode as first message (can only be Login or Resume)",
        )


@dataclass
class WebsocketConnectionState:
    """Holds specific state about this connection"""

    user: User
    session_id: str
    heartbeat_wait_task: Optional[asyncio.Task]


async def do_main_loop():

    # when we connect, it is possible there are leftover tasks from an old
    # connection. to keep them as singletons (as in, only one of those tasks
    # can exist in the system), we attempt to communicate the ReplacedTask
    # exception.

    user = g.state.user

    task_ids = (
        (f"queue_worker:{user.id}"),
        (f"receiver_worker:{user.id}"),
        (f"heartbeat:{user.id}"),
    )

    for task_id in task_ids:
        app.sched.stop(task_id)

    tasks = [
        app.sched.spawn(
            queue_processor,
            [g.state],
            name=f"queue_worker:{user.id}",
            fail_mode=WebsocketFailMode(),
        ),
        app.sched.spawn(
            receiver_worker,
            [g.state],
            name=f"receiver_worker:{user.id}",
            fail_mode=WebsocketFailMode(),
        ),
        app.sched.spawn(
            heartbeat,
            [g.state],
            name=f"heartbeat:{user.id}",
            fail_mode=WebsocketFailMode(),
        ),
    ]

    pending = None

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        log.info(
            "unexpected websocket task finish for user %s. %d done %d pending",
            user.id,
            len(done),
            len(pending),
        )

        # if any task raises WebsocketClose, we should re-raise it up via result()
        for task in done:
            task.result()
    except asyncio.CancelledError:
        raise WebsocketClose(
            CloseCodes.ERROR, "Unexpected task cancellation. Connection likely broken"
        )
    finally:
        # if any task stopped, also stop the rest (only when required)
        if pending:
            for task in tasks:
                app.sched.stop(task.get_name())


class ControlMessageType(Enum):
    SEND = 0


async def queue_processor(state):
    while True:
        session = app.sessions.get_by_user(state.user.id)
        queue = session.queue

        assert queue is not None
        control_message = await queue.get()
        log.info("got control message %r", control_message)
        dispatch_type, data = control_message

        if dispatch_type == 1:
            request_id = data
            req = app.sessions.requests[request_id]
            await send_op(
                OperationType.HTTP_REQUEST,
                {
                    "request_id": request_id,
                    "path": req.path,
                    "headers": req.headers,
                    "body": req.body,
                },
            )

        queue.task_done()


async def heartbeat_wait_ack():
    await asyncio.sleep(20)
    raise WebsocketClose(
        CloseCodes.HEARTBEAT_EXPIRE, "timed out waiting for heartbeat ack"
    )


async def heartbeat(state):
    while True:
        await asyncio.sleep(10)
        await send_op(OperationType.HEARTBEAT, None)

        # spawn a task that waits for the timeout and deletes the vpn.
        #
        # if we get a heartbeat_ack in time, the task is cancelled by
        # receiver_worker, and so we don't delete the vpn :D
        #
        # we keep it as a 'singleton' task which means only one of them
        # must exist waiting for the ack.
        if state.heartbeat_wait_task is not None:
            state.heartbeat_wait_task = app.sched.spawn(
                heartbeat_wait_ack, [], name=f"heartbeat_wait:{state.user.id}"
            )

            try:
                await state.heartbeat_wait_task
            except asyncio.CancelledError:
                # cancellation is the happy path
                pass


async def process_incoming_message(state, message):
    try:
        opcode = OperationType(message["op"])
    except ValueError:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Unknown opcode value")

    if opcode == OperationType.HEARTBEAT_ACK:
        if state.heartbeat_wait_task is not None:
            state.heartbeat_wait_task.cancel()
    elif opcode == OperationType.HTTP_RESPONSE:
        data = message["d"]

        request_id = data["request_id"]
        incoming_request = app.sessions.requests.get(request_id)
        if incoming_request is None:
            log.warning("client attempted to reply to unknown request")
            return

        if incoming_request.session_id != g.state.session_id:
            log.warning("client attempted to reply to unowned request")
            return

        incoming_request.response = data["response"]
        incoming_request.response_event.set()
    else:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Invalid opcode value")


async def receiver_worker(state):
    while True:
        message = await receive_any()

        try:
            await process_incoming_message(state, message)
        except WebsocketClose as exc:
            raise exc
        except Exception as exc:
            log.exception("error handling message")
            raise WebsocketClose(CloseCodes.ERROR, f"error: {exc!r}")


@bp.websocket("/control")
async def control():
    """Entrypoint for the Control API."""
    try:
        await do_login()
        await do_main_loop()
        await websocket.close(4000, reason="unknown error")
    except WebsocketClose as close:
        log.warning("ws close code=%d reason=%r", close.code, close.reason)
        await websocket.close(code=close.code, reason=close.reason)
    except Exception as exc:
        log.exception("error on websocket handling")
        await websocket.close(4000, reason=repr(exc))
