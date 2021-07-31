# asot: Localhost tunneling
# Copyright 2021, Luna and asot contributors
# SPDX-License-Identifier: BSD-3-Clause


class APIError(Exception):
    status_code = 500

    def get_payload(self):
        return {}
