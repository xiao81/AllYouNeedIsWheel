#!/usr/bin/env python3
"""Run the local Wheel workspace. Broker setup is available at /settings."""

import argparse
import errno
import os
import platform
import socket
import subprocess
import sys
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Start the Wheel options workspace")
    parser.add_argument(
        "--realmoney",
        action="store_true",
        help="Select the saved Live profile on startup",
    )
    args = parser.parse_args()
    try:
        port = int(os.environ.get("PORT", 8000))
        workers = int(os.environ.get("WORKERS", 1))
        if not 1 <= port <= 65535 or workers < 1:
            raise ValueError
    except ValueError:
        parser.error("PORT must be 1–65535 and WORKERS must be positive")
    # Check before changing the saved profile or importing the application.
    # Gunicorn still performs the authoritative bind if another process races us.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            print(
                f"Port {port} is already in use. Wheel was not started.\n"
                f"If Wheel is already running, open http://127.0.0.1:{port}.\n"
                "Otherwise stop the existing server before trying again.\n"
                f"Inspect it with: lsof -nP -iTCP:{port} -sTCP:LISTEN\n"
                "To use another port: PORT=8080 python3 run_api.py",
                file=sys.stderr,
            )
        else:
            print(f"Cannot bind to 127.0.0.1:{port}: {error}", file=sys.stderr)
        return 1
    if args.realmoney:
        from core.settings import read_profiles, save_profiles

        settings = read_profiles()
        settings["mode"] = "live"
        save_profiles(settings)
    print(
        f"Wheel: http://127.0.0.1:{port} · Setup: http://127.0.0.1:{port}/settings",
        flush=True,
    )
    if platform.system() == "Windows":
        from waitress import serve
        from app import app

        serve(app, host="127.0.0.1", port=port, threads=4)
    else:
        # HTTP threads remain responsive while broker work stays on its own loop.
        # One process shares metadata and quote caches across the whole workspace.
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "gunicorn",
                f"--workers={workers}",
                "--threads=4",
                "--timeout=120",
                f"--bind=127.0.0.1:{port}",
                "app:app",
            ],
            check=False,
        )
        if result.returncode:
            print("Wheel stopped. See the server error above.", file=sys.stderr)
        return result.returncode
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
