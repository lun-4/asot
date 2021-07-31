# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


import pytest

pytestmark = pytest.mark.asyncio


async def test_universe():
    assert 1 == 1
