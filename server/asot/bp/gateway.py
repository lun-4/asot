# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause

import base64
import asyncio

from quart import Blueprint, request, current_app as app, make_response

bp = Blueprint("gateway", __name__)

# asot works internally by tagging a request based on its Host header
#
# if Host is the actual host set in config, it keeps rerouting properly
# else, we must reroute to a connected client


@bp.before_app_request
async def on_request():
    request_host = request.headers["host"]
    api_domain = app.cfg["asot"]["api_domain"]

    # if its an exact match, follow thru to api
    # if not, its possibly a domain reroute to someone's tunnel
    if request_host == api_domain:
        return

    # urls pointing to tunnels are in the format [sesion_id].[api_host]
    # like this:
    #  https://1fh451v.asot.site

    if not request_host.endswith(api_domain):
        return "invalid asot domain", 400

    session_id, *_rest = request_host.split(".")
    return await reroute(session_id)


async def reroute(session_id):

    # reroutes work like this:
    # - create a request on the queue of the session
    # - the queue_worker on the control bp is going to translate the internal
    #   "we have a request" python essage to a "we have a request" websocket message
    # - the client replies with http response websocket message
    # - the receiver_worker task finds the request object and sets the event
    # - WE MUST CLEAN THE REQUEST OBJECT AFTERWARDS

    session = app.sessions.get_by_id(session_id)
    if session is None:
        return "session not found", 404

    request_id = await app.sessions.send_request(session_id)
    req = app.sessions.requests[request_id]
    try:
        await asyncio.wait_for(req.response_event.wait(), timeout=30)
        # since we need to clean everything up, make a copy of the
        # response so we can reply with a quart response, while also being
        # able to pop() the request from the system
        client_response = dict(req.response)
    except asyncio.TimeoutError:
        return "asot client timed out", 502
    finally:
        app.sessions.requests.pop(request_id)

    # convert from internal response object to quart response
    body = base64.b64decode(client_response["body"]).decode()
    final_response = await make_response((body, client_response["status_code"]))
    for key, value in client_response["headers"].items():
        final_response.headers[key] = value
    return final_response
