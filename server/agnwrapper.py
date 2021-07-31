#!/usr/bin/env python3

# agnwrapper - agnostic Wrapper
# Reads the app's config file and then runs agnostic with the desired
# command line arguments.

import sys
import shlex
import subprocess
import time
import json
from pathlib import Path

from tomlkit import parse


def main():
    with open("./config.toml", "r") as config_file:
        config = parse(config_file.read())

    db = config["database"]
    filepath = db["filepath"]

    args = [
        "agnostic",
        "-t",
        "sqlite",
        "-d",
        filepath,
    ]

    if not sys.argv[1:]:
        print(
            "agnwrapper: use an argument to do an operation. "
            "do --help to see agnostic helptext"
        )
        return

    if sys.argv[1] == "create_migration":
        migration_name = sys.argv[2]
        timestamp = int(time.time())

        migration_folder = Path("./migrations")
        migration_folder.mkdir(exist_ok=True)
        migration_filename = f"{timestamp}_{migration_name}.sql"
        f = open(migration_folder / migration_filename, "w")
        f.close()

        print("created migration:", migration_filename)

        return

    for arg in sys.argv[1:]:
        args.append(arg)

    joined = shlex.join(args)
    print("agnwrapper: running", repr(joined))
    proc = subprocess.Popen(args)
    proc.communicate()


if __name__ == "__main__":
    main()
