# bbv: Server component for bigbigvpn
# Copyright 2021, Team bigbigvpn and bbv contributors
# SPDX-License-Identifier: AGPL-3.0-only

import json
import asyncio
import logging
import uuid
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from quart import Blueprint, websocket, current_app as app, g
import violet.fail_modes

from asot.models import User
from asot.errors import FailedAuth
from asot.enums.messages import (
    CommandType,
    OperationType,
    NotifyType,
    RunningVPNMessageType,
    CloseCodes,
)


bp = Blueprint(__name__, "control")
log = logging.getLogger(__name__)


async def receive_any():
    data_str = await websocket.receive()
    log.debug("got message: %r", data_str)
    try:
        data = json.loads(data_str)
        return data
    except json.JSONDecodeError:
        raise WebsocketClose(CloseCodes.INVALID_JSON, "Invalid JSON")


async def recv_op(op: OperationType):
    data = await receive_any()
    if "op" not in data:
        raise WebsocketClose(
            CloseCodes.INVALID_MESSAGE, "Invalid Message (no op field)"
        )

    if "d" not in data:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Invalid Message (no d field)")

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


async def send_dispatch(cmd: CommandType, data: dict):
    message = {
        "op": OperationType.COMMAND.value,
        "d": {"t": cmd.value, "v": data},
    }
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

    async def handle(self, job, exc, _state) -> bool:
        if isinstance(exc, WebsocketClose):
            raise exc
        else:
            await violet.fail_modes.LogOnly().handle(job, exc, _state)


async def do_login():
    await websocket.accept()
    login = await recv_op(OperationType.LOGIN, LOGIN_SCHEMA)
    user_id = hello["user_id"]

    try:
        user = await User.fetch(user_id)
    except FailedAuth as exc:
        raise WebsocketClose(CloseCodes.FAILED_AUTH, exc.get_message())

    g.state = WebsocketConnectionState(user, None)
    await send_op(OperationType.WELCOME, None)


@dataclass
class WebsocketConnectionState:
    """Holds specific state about this connection"""

    user: User
    heartbeat_wait_task: Optional[asyncio.Task]


async def do_main_loop():

    # when we connect, it is possible there are leftover tasks from an old
    # connection. to keep them as singletons (as in, only one of those tasks
    # can exist in the system), we attempt to communicate the ReplacedTask
    # exception.

    user = g.state.user

    task_ids = (
        f"queue_worker:{user.id}",
        (f"receiver_worker:{user.id}"),
        (f"heartbeat:{user.id}"),
    )

    for task_id in task_ids:
        existing_task = app.sched.tasks.get(task_id)
        if existing_task is None:
            continue
        existing_task.cancel(msg="replaced")

    tasks = [
        app.sched.spawn(
            queue_processor,
            [g.vpn],
            name=f"queue_worker:{g.vpn.id}",
            fail_mode=WebsocketFailMode(),
        ),
        app.sched.spawn(
            receiver_worker,
            [g.state],
            name=f"receiver_worker:{g.vpn.id}",
            fail_mode=WebsocketFailMode(),
        ),
        app.sched.spawn(
            heartbeat,
            [g.state],
            name=f"heartbeat:{g.vpn.id}",
            fail_mode=WebsocketFailMode(),
        ),
    ]

    pending = None

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        log.info(
            "unexpected websocket task finish for user %s. %d done %d pending",
            g.vpn.id,
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


async def queue_processor(vpn):
    while True:
        running_state = app.running_vpns.vpns[vpn.id]
        queue = running_state.queue

        assert queue is not None
        control_message = await queue.get()
        log.info("got control message %r", control_message)
        dispatch_type, data = control_message

        if dispatch_type == RunningVPNMessageType.COMMAND:
            command_type, command_data = data
            await send_dispatch(command_type, command_data)
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
                heartbeat_wait_ack, [], name=f"heartbeat_wait:{state.vpn.id}"
            )

            try:
                await state.heartbeat_wait_task
            except asyncio.CancelledError:
                # cancellation is the happy path
                pass


async def process_single_message(state, message):
    try:
        opcode = OperationType(message["op"])
    except ValueError:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Unknown opcode value")

    if opcode == OperationType.HEARTBEAT_ACK:
        if state.heartbeat_wait_task is not None:
            state.heartbeat_wait_task.cancel()
    elif opcode == OperationType.NOTIFY:
        notify_type = NotifyType(message["d"]["t"])

        # for now, since we have only a single notification, data is basically
        # nothing
        # notify_data = message["d"]["v"]

        if notify_type == NotifyType.NO_CLIENTS:
            log.info("vpn %r signaled it has no clients. destroying vpn", state.vpn)
            await state.vpn.delete()
    else:
        raise WebsocketClose(CloseCodes.INVALID_MESSAGE, "Invalid opcode value")


async def receiver_worker(state):
    while True:
        message = await receive_any()

        try:
            await process_single_message(state, message)
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
        await websocket.send(4000, reason=repr(exc))
