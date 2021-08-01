# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


import secrets
from typing import Optional, Tuple
from dataclasses import dataclass

from quart import current_app as app


@dataclass
class User:
    id: str
    username: str
    email: str

    @classmethod
    def from_row(_cls, row: Optional[Tuple]) -> Optional["User"]:
        return User(*row) if row is not None else None

    @classmethod
    async def fetch(_cls, user_id: str) -> Optional["User"]:
        async with app.db.execute(
            """
            SELECT
                id, username, email
            FROM asot_users
            WHERE id = ?
            """,
            (user_id,),
        ) as cursor:
            return User.from_row(await cursor.fetchone())

    @classmethod
    async def create(_cls, *, username: str, email: str) -> "User":
        async with app.db.execute(
            """
            INSERT INTO asot_users
                (id, username, email)
            VALUES
                (?, ?, ?)
            RETURNING
                id, username, email
            """,
            (
                secrets.token_urlsafe(32),
                username,
                email,
            ),
        ) as cur:
            row = await cur.fetchone()
            assert row is not None
            return User.from_row(row)

    def to_dict(self):
        return {
            "id": str(self.id),
            "username": self.username,
            "email": self.email,
        }
