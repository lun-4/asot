# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause

import asyncio
import argparse

import aiosqlite
from tomlkit import parse
from quart import Quart, current_app

from asot.models import User


async def adduser(args):
    user = await User.create(email=args.email, username=args.username)
    print("ok", user.id)


async def help_text(_args):
    current_app.manage_parser.print_help()


async def amain():
    parser = argparse.ArgumentParser()
    parser.set_defaults(func=help_text)
    subparsers = parser.add_subparsers(help="operations")

    parser_adduser = subparsers.add_parser(
        "adduser",
        help="Add a single user",
    )
    parser_adduser.add_argument("email", help="User's email")
    parser_adduser.add_argument("username", help="User's new username")
    parser_adduser.set_defaults(func=adduser)

    app = Quart(__name__)

    # inject services into fake app variable
    with open("./config.toml", "r") as config_file:
        app.cfg = parse(config_file.read())

    async with aiosqlite.connect(app.cfg["database"]["filepath"]) as db:
        app.db = db
        app.manage_parser = parser
        app.sched = None

        args = parser.parse_args()
        print(args)
        async with app.app_context():
            await args.func(args)
            await app.db.commit()


def main():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(amain())
