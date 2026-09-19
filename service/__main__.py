from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from service.auth import hash_password, validate_username
from service.config import load_gateway_config
from service.server import GatewayHandler, bootstrap_admin, serve
from service.storage import Store


def cmd_serve(_args: argparse.Namespace) -> int:
    config = load_gateway_config()
    server = serve(config)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nGateway stopped.")
    finally:
        jobs = getattr(GatewayHandler, "jobs", None)
        if jobs is not None:
            jobs.stop()
        server.server_close()
    return 0


def cmd_add_user(args: argparse.Namespace) -> int:
    config = load_gateway_config()
    store = Store(config)
    bootstrap_admin(config, store)
    username = validate_username(args.username)
    password = args.password or getpass.getpass("Password: ")
    salt, digest = hash_password(password)
    store.create_user(username, digest, salt, args.role)
    print(f"Created {args.role} {username}")
    return 0


def cmd_cleanup(_args: argparse.Namespace) -> int:
    from service.jobs import JobManager

    config = load_gateway_config()
    store = Store(config)
    manager = JobManager(config, store)
    result = manager.cleanup_once()
    print(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AutoRecon authenticated job gateway.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Run the local gateway (default bind 127.0.0.1).")
    add_user = sub.add_parser("add-user", help="Create a gateway user.")
    add_user.add_argument("--username", required=True)
    add_user.add_argument("--password")
    add_user.add_argument("--role", choices=("user", "admin"), default="user")
    sub.add_parser("cleanup", help="Delete expired jobs and incomplete uploads.")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args)
    if args.command == "add-user":
        return cmd_add_user(args)
    if args.command == "cleanup":
        return cmd_cleanup(args)
    return 2


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
