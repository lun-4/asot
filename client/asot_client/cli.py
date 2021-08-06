# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause
import sys
import base64
import argparse
import logging
import asyncio
import json

import httpx
import websockets

log = logging.getLogger(__name__)


class APIClient:
    def __init__(self, server_url):
        self.server_url = f"{server_url}/api/dev"
        self.httpx = httpx.AsyncClient()

    async def close(self):
        await self.httpx.aclose()

    async def _maybe_error_on_response(self, resp):
        if resp.status_code not in (200, 201):
            body = resp.content
            raise Exception(f"api error: {resp.status_code} {body}")
        return resp.json()

    async def get_user(self, user_id):
        resp = await self.httpx.get(f"{self.server_url}/user/{user_id}")
        return await self._maybe_error_on_response(resp)


async def send_json(ws, obj):
    log.info("ws: sending %r", obj)
    await ws.send(json.dumps(obj))


async def recv_json(ws):
    msg = await ws.recv()
    log.info("ws: received %r", msg)
    return json.loads(msg)


async def send_http_response(websocket, request_id, status_code, headers, body_string):
    body = base64.b64encode(body_string).decode()

    await send_json(
        websocket,
        {
            "op": 6,
            "d": {
                "request_id": request_id,
                "response": {
                    "status_code": status_code,
                    "headers": headers,
                    "body": body,
                },
            },
        },
    )


class OperationType(Enum):
    LOGIN = 1
    WELCOME = 2
    HEARTBEAT = 3
    HEARTBEAT_ACK = 4
    HTTP_REQUEST = 5
    HTTP_RESPONSE = 6
    RESUME = 7


class CloseCodes:
    ERROR = 4000
    FAILED_AUTH = 4001
    HEARTBEAT_EXPIRE = 4002
    INVALID_JSON = 4003
    INVALID_MESSAGE = 4004


async def async_main():
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(description="asot client")
    parser.add_argument("server_url", help="asot server url")
    parser.add_argument("user_id", help="user id logging in to asot")
    parser.add_argument("port", type=int, help="port to tunnel in localhost")

    args = parser.parse_args()

    api = APIClient(args.server_url)
    # user = await api.get_user(args.user_id)
    # print(user)

    # TODO: parse given server url so we can change scheme in a safer manner
    async with websockets.connect(
        f"{api.server_url}/control".replace("http", "ws")
    ) as websocket:

        # after LOGIN, assert we get a WELCOME
        await send_json(
            websocket, {"op": OperationType.LOGIN, "d": {"user_id": args.user_id}}
        )
        reply = await recv_json(websocket)
        opcode = OperationType(reply["op"])
        assert opcode == OperationType.WELCOME

        while True:
            reply = await recv_json(websocket)
            if opcode == OperationType.HEARTBEAT:
                await send_json(
                    websocket, {"op": OperationType.HEARTBEAT_ACK, "d": None}
                )
            elif opcode == OperationType.HTTP_REQUEST:
                data = reply["d"]
                path = data["path"]
                headers = data["headers"]
                # TODO give body to request
                try:
                    resp = await api.httpx.get(
                        f"http://localhost:{args.port}{path}", headers=headers
                    )

                    await send_http_response(
                        websocket,
                        data["request_id"],
                        resp.status_code,
                        dict(resp.headers),
                        resp.content,
                    )

                except httpx.RequestError as exc:
                    await send_http_response(
                        websocket,
                        data["request_id"],
                        502,
                        {"Reply-By-Client": 1},
                        b"failed to connect to webapp",
                    )


def main_cli():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(async_main())
