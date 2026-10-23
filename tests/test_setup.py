from http.client import HTTPConnection
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from oh_my_agent_zero import cli, setup_ui


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SetupTests(unittest.TestCase):
    def request(self, port, headers=None, path="/"):
        connection = HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_progress_and_local_request_boundary(self):
        port = free_port()
        with setup_ui.setup_page(port, open_browser=False) as progress:
            code, headers, body = self.request(port)
            self.assertEqual(code, 200)
            self.assertIn(b"Preparing Agent Zero", body)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["X-OMA0-Setup"], "1")
            progress("Checking the upstream runtime...")
            _, _, body = self.request(port, {"Accept": "application/json"})
            self.assertEqual(json.loads(body), {"stage": "Checking the upstream runtime...", "failed": False})
            for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
                self.assertEqual(self.request(port, headers)[0], 403)
            self.assertEqual(self.request(port, path="/state.json")[0], 404)
        with self.assertRaises(OSError):
            self.request(port)

    def test_failure_is_visible_until_ctrl_c_then_exits_with_error(self):
        port = free_port()

        def interrupt(_):
            _, _, body = self.request(port, {"Accept": "application/json"})
            self.assertTrue(json.loads(body)["failed"])
            self.assertNotIn("private", body.decode())
            raise KeyboardInterrupt

        with patch.object(setup_ui.time, "sleep", side_effect=interrupt):
            with self.assertRaisesRegex(RuntimeError, "private diagnostic"):
                with setup_ui.setup_page(port, open_browser=False):
                    raise RuntimeError("private diagnostic")

    def test_occupied_port_never_runs_installer(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            with patch.object(cli, "install") as install:
                with self.assertRaises(SystemExit):
                    cli.main(["--home", folder, "start", "--no-browser", "--port", str(occupied.getsockname()[1])])
                install.assert_not_called()

    def test_first_start_reuses_installer_then_hands_off_and_skips_setup_next_time(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            port = free_port()
            state = {"revision": "upstream"}

            def prepare(target, *, progress):
                self.assertEqual(target, home.resolve())
                self.assertEqual(self.request(port)[0], 200)
                with self.assertRaisesRegex(RuntimeError, "Stop it first"):
                    with cli.locked(target):
                        pass
                progress("Installing core dependencies...")
                cli.save_state(home, state)

            def serve(*args):
                with self.assertRaises(OSError):
                    self.request(port)

            with patch.object(cli, "install", side_effect=prepare) as install, patch.object(cli, "git", return_value="upstream"), patch.object(cli, "serve", side_effect=serve) as run:
                for _ in range(2):
                    cli.main(["--home", folder, "start", "--no-browser", "--port", str(port)])
                self.assertEqual(install.call_count, 1)
                self.assertEqual(run.call_count, 2)

    def test_invalid_port_rejected_before_installation(self):
        with patch.object(cli, "install") as install:
            with self.assertRaises(SystemExit):
                cli.main(["start", "--port", "0"])
            install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
