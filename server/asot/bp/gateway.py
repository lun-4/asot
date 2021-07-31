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
    api_host = app.cfg["asot"]["api_host"]

    if request_host == api_host:
        return

    # TODO: reroute
    return
