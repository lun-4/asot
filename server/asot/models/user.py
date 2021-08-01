# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


import uuid
import secrets
from typing import Optional
from dataclasses import dataclass


@dataclass
class User:
    id: uuid.UUID
    username: str
    email: str

    @classmethod
    def from_row(_cls, row: Optional[dict]) -> Optional["User"]:
        return User(**row) if row is not None else None

    @classmethod
    async def fetch(_cls, user_id: uuid.UUID) -> Optional["User"]:
        async with app.db.execute(
            """
            SELECT
                id, username, email
            FROM asot_users
            WHERE id = $1
            """,
            user_id,
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