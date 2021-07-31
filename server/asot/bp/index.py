# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


from quart import Blueprint

bp = Blueprint("index", __name__)


@bp.route("/", methods=["GET"])
async def index_route():
    return "nyanya"
