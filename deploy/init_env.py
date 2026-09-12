"""Create a private deployment env once; never prints or replaces secrets."""

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-origin", default="http://localhost:18080")
    args = parser.parse_args()
    origin = urlsplit(args.web_origin)
    if (
        not origin.hostname
        or origin.username
        or origin.password
        or origin.path
        or origin.query
        or origin.fragment
        or origin.scheme not in {"http", "https"}
        or (
            origin.scheme == "http"
            and origin.hostname not in {"localhost", "127.0.0.1"}
        )
    ):
        parser.error("web-origin must be an HTTPS origin, or local loopback HTTP, without a trailing slash")
    directory = Path(__file__).resolve().parent
    target = directory / ".env"
    values = {
        key: secrets.token_urlsafe(36)
        for key in (
            "MYSQL_PASSWORD",
            "MYSQL_ROOT_PASSWORD",
            "JWT_SECRET",
            "EVAL_WORKER_TOKEN",
            "EMAIL_CODE_SECRET",
            "REDIS_PASSWORD",
            "REDIS_CACHE_PASSWORD",
            "QDRANT_API_KEY",
            "QDRANT_READ_ONLY_API_KEY",
        )
    }
    values["WEB_ORIGINS"] = json.dumps([args.web_origin], separators=(",", ":"))
    text = (directory / "env.example").read_text(encoding="utf-8")
    rendered = "\n".join(
        f"{line.split('=', 1)[0]}={values[line.split('=', 1)[0]]}"
        if "=" in line and line.split("=", 1)[0] in values
        else line
        for line in text.splitlines()
    ) + "\n"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        parser.error("deploy/.env already exists; edit it explicitly instead of replacing credentials")
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    print("Created deploy/.env with new independent secrets; no secret values were printed.")


if __name__ == "__main__":
    main()
