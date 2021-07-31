# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


import logging
from typing import Tuple

import quart
import aiosqlite
from quart import jsonify
from tomlkit import parse

from .errors import APIError

from .bp import index


log = logging.getLogger(__name__)
ROOT_PREFIXES = ("/api/dev",)


def create_app() -> quart.Quart:
    app = quart.Quart(__name__)
    with open("./config.toml", "r") as config_file:
        app.cfg = parse(config_file.read())

    logging.basicConfig(level="INFO")
    return app


def setup_blueprints(app: quart.Quart) -> None:
    # use None to load the blueprint under /
    # use an empty string to load the blueprint under /api
    # use a non-empty string to load the blueprint under /api<your string>
    blueprint_list = [
        (index, None),
    ]

    for blueprint, api_prefix in blueprint_list:
        route_prefixes = [f'{root}{api_prefix or ""}' for root in ROOT_PREFIXES]

        if api_prefix is None:
            route_prefixes = [""]

        log.debug(
            "loading blueprint %r with prefixes %r", blueprint.name, route_prefixes
        )
        for route in route_prefixes:
            app.register_blueprint(blueprint, url_prefix=route)


app = create_app()


@app.before_serving
async def app_before_serving():
    log.info("opening db")
    app.db = await aiosqlite.connect(app.cfg["database"]["filepath"])


@app.after_serving
async def close_db():
    """Close all database connections."""
    log.info("closing db")
    await app.db.close()


@app.errorhandler(404)
async def handle_notfound(_err):
    return "Not Found", 404


@app.errorhandler(500)
def handle_exception(exception):
    """Handle any kind of exception."""
    status_code = 500

    try:
        status_code = exception.status_code
    except AttributeError:
        pass

    return (
        jsonify(
            {
                "error": True,
                "message": repr(exception),
            }
        ),
        status_code,
    )


def _wrap_err_in_json(err: APIError) -> Tuple[quart.wrappers.Response, int]:
    res = {
        "error": True,
        "message": err.args[0],
    }
    res.update(err.get_payload())
    return jsonify(res), err.status_code


@app.errorhandler(APIError)
def handle_api_error(err: APIError):
    """Handle any kind of application-level raised error."""
    log.warning(f"API error: {err!r}")

    return _wrap_err_in_json(err)


setup_blueprints(app)
