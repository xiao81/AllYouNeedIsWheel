"""Launcher failures must not start a second server or switch account profiles."""

import contextlib
import io
import socket
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import run_api


class LauncherTests(unittest.TestCase):
    def test_busy_port_exits_before_profile_change(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            settings = MagicMock()
            output = io.StringIO()
            with (
                patch.object(run_api, "load_dotenv"),
                patch.dict("os.environ", {"PORT": str(port), "WORKERS": "1"}),
                patch("sys.argv", ["run_api.py", "--realmoney"]),
                patch.dict("sys.modules", {"core.settings": settings}),
                patch.object(run_api.subprocess, "run") as start,
                contextlib.redirect_stderr(output),
            ):
                self.assertEqual(run_api.main(), 1)
            self.assertIn(f"Port {port} is already in use", output.getvalue())
            settings.save_profiles.assert_not_called()
            start.assert_not_called()

    def test_server_failure_returns_exit_code_without_traceback(self):
        output = io.StringIO()
        with (
            patch.object(run_api, "load_dotenv"),
            patch.dict("os.environ", {"PORT": "8000", "WORKERS": "1"}),
            patch("sys.argv", ["run_api.py"]),
            patch.object(run_api.socket, "socket"),
            patch.object(run_api.platform, "system", return_value="Darwin"),
            patch.object(
                run_api.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 1),
            ),
            contextlib.redirect_stderr(output),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(run_api.main(), 1)
        self.assertIn("See the server error above", output.getvalue())


if __name__ == "__main__":
    unittest.main()
