# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


from quart import Blueprint, request, current_app as app

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
    # once we get a reroute, create a request on the session manager,
    # it will dispatch to the queue, and then we wait for a response
    request_id = await app.sessions.send_request(session_id)
    req = app.sessions.requests[request_id]
    # TODO timeouts, clean it all up afterwards
    await req.response_event.wait()

    # once the event is set, we must have a response
    # copy the object so that we can clean it up on the session store
    # before we return it to the client

    response_copy = dict(req.response)
    app.sessions.requests.pop(request_id)
    return repr(response_copy), 200
