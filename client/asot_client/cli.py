# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause
import sys
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
    await ws.send(json.dumps(obj))


async def recv_json(ws):
    msg = await ws.recv()
    return json.loads(msg)


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
        await send_json(websocket, {"op": 1, "d": {"user_id": args.user_id}})
        reply = await recv_json(websocket)
        assert reply["op"] == 2
        while True:
            reply = await recv_json(websocket)
            if reply["op"] == 3:
                await send_json(websocket, {"op": 4, "d": None})
            elif reply["op"] == 5:
                data = reply["d"]
                path = data["path"]
                headers = data["headers"]
                # TODO body etc
                resp = await api.httpx.get(
                    f"http://localhost:{port}{path}", headers=headers
                )
                await send_json(
                    websocket,
                    {
                        "op": 6,
                        "d": {
                            "request_id": data["request_id"],
                            "status_code": resp.status_code,
                            "headers": dict(resp.headers),
                            "content": await resp.content,
                        },
                    },
                )


def main_cli():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(async_main())
