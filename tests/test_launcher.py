import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oh_my_agent_zero import cli, native


class NativeTests(unittest.TestCase):
    def test_path_mapping_preserves_external_paths(self):
        root = Path(tempfile.gettempdir()) / "native folder"
        self.assertEqual(native.native_path("/a0/usr/workdir", root), str(root / "usr/workdir"))
        self.assertEqual(native.native_path("usr/workdir", root), str(root / "usr/workdir"))
        self.assertEqual(native.native_path("/a0", root), str(root))
        external = str(Path(tempfile.gettempdir()) / "outside")
        self.assertEqual(native.native_path(external, root), external)

    def test_windows_quotes_and_call_operator(self):
        self.assertEqual(native.shell_command(["C:\\My Apps\\python.exe", "a'b\"$x"], windows=True),
                         "& 'C:\\My Apps\\python.exe' 'a''b\"$x'")

    def test_posix_arguments_roundtrip(self):
        import shlex
        args = ["/tmp/My Apps/python", "a'b\"$x\nline two"]
        self.assertEqual(shlex.split(native.shell_command(args, windows=False)), args)

    def test_payload_not_interpreted_by_shell(self):
        with patch.dict(os.environ, {"OMA0_EXECUTION_PYTHON": "python", "OMA0_NODE": "node"}):
            for language in ("python", "nodejs"):
                command = native.execution_command(language, "'\"$(echo bad)\n café", Path("/tmp/root"))
                self.assertNotIn("$(echo bad)", command)
                self.assertNotIn("\n", command)

    def test_install_failure_restores_code_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "source").mkdir()
            state = {"revision": "old", "branch": "main", "framework": "old-env", "node": "node"}
            cli.save_state(home, state)
            calls = []

            def git(source, *args):
                if args[0] == "remote":
                    return cli.UPSTREAM
                if args[0] == "status":
                    return ""
                return "old" if args[-1] == "HEAD" else "new"

            def run(*args, **kwargs):
                calls.append(tuple(map(str, args)))
                if args[:3] == ("uv", "pip", "install"):
                    raise RuntimeError("dependency install failed")

            with patch.object(cli.shutil, "which", return_value="tool"), patch.object(cli, "git", side_effect=git), patch.object(cli, "run", side_effect=run):
                with self.assertRaisesRegex(RuntimeError, "dependency install failed"):
                    cli.install(home, update=True)
            self.assertEqual(cli.read_state(home), state)
            self.assertEqual(calls[-1], ("git", "-C", str(home / "source"), "checkout", "--detach", "old"))

    def test_dirty_source_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "source").mkdir()
            with patch.object(cli.shutil, "which", return_value="tool"), patch.object(cli, "git", side_effect=[cli.UPSTREAM, " M agent.py"]), patch.object(cli, "run") as run:
                with self.assertRaisesRegex(RuntimeError, "local changes"):
                    cli.install(home)
                run.assert_not_called()

    def test_state_write_and_missing_install(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "install"):
                cli.read_state(home)
            cli.save_state(home, {"revision": "example"})
            self.assertEqual(cli.read_state(home)["revision"], "example")
            self.assertFalse((home / "state.tmp").exists())

    def test_process_lock_rejects_second_owner(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            with cli.locked(Path(folder)):
                result = subprocess.run([sys.executable, "-c",
                    "from oh_my_agent_zero.cli import locked; from pathlib import Path; "
                    f"ctx=locked(Path({folder!r})); ctx.__enter__()"], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Stop it first", result.stderr)


if __name__ == "__main__":
    unittest.main()
