import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch, Mock

from oh_my_agent_zero import cli, native, windows


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

    @unittest.skipIf(os.name == "nt", "POSIX shell behavior")
    def test_prompt_survives_bash_as_the_intermediate_shell(self):
        import subprocess
        result = subprocess.run(["/bin/bash", "--posix", "-c", native.terminal_command()],
                                input="exit\n", text=True, capture_output=True, timeout=10)
        self.assertIn("a0@native:", result.stderr)

    def test_payload_not_interpreted_by_shell(self):
        with patch.dict(os.environ, {"OMA0_EXECUTION_PYTHON": "python", "OMA0_NODE": "node"}):
            for language in ("python", "nodejs"):
                command = native.execution_command(language, "'\"$(echo bad)\n café", Path("/tmp/root"))
                self.assertNotIn("$(echo bad)", command)
                self.assertNotIn("\n", command)

    def test_alias_mapping_does_not_change_file_contents_or_external_paths(self):
        root = Path(tempfile.gettempdir()) / "native"
        self.assertEqual(native.map_alias(["/a0/usr/a.txt", "s3://bucket/a", "text /a0/a"], root),
                         [str(root / "usr/a.txt"), "s3://bucket/a", "text /a0/a"])

    def test_supervisor_restarts_only_for_requested_exit_code(self):
        children = [Mock(), Mock()]
        for child, code in zip(children, (75, 0)):
            child.wait.return_value = code
            child.poll.return_value = code
        with patch.object(cli.subprocess, "Popen", side_effect=children) as spawn:
            cli.serve(Path(tempfile.gettempdir()), {"node": "node", "framework": "framework"}, 50001)
            self.assertEqual(spawn.call_count, 2)
            self.assertEqual(spawn.call_args.kwargs["env"]["OMA0_SUPERVISED"], "1")

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

    def test_failed_windows_replace_preserves_existing_chat(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "chat.json"
            target.write_text("old")
            with patch.object(windows, "move_atomic", side_effect=OSError("locked")):
                with self.assertRaisesRegex(OSError, "locked"):
                    windows.write_text_atomic(target, "new")
            self.assertEqual(target.read_text(), "old")
            self.assertEqual(list(Path(folder).iterdir()), [target])

    @unittest.skipUnless(os.name == "nt", "Windows atomic replacement")
    def test_windows_atomic_save_replaces_and_flushes(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "chat café.json"
            windows.write_text_atomic(target, "first")
            windows.write_text_atomic(target, "second")
            self.assertEqual(target.read_text(), "second")
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_real_git_update_and_failed_candidate_preserve_user_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            upstream, home = root / "upstream", root / "install"
            upstream.mkdir()
            def git_at(path, *args):
                return subprocess.check_output(["git", "-C", str(path), *args], stderr=subprocess.DEVNULL, text=True).strip()
            git_at(upstream, "init", "-b", "main")
            git_at(upstream, "config", "user.name", "Native test")
            git_at(upstream, "config", "user.email", "native@example.invalid")
            (upstream / "requirements.txt").write_text("")
            git_at(upstream, "add", ".")
            git_at(upstream, "commit", "-m", "baseline")
            home.mkdir()
            subprocess.run(["git", "clone", str(upstream), str(home / "source")], check=True, capture_output=True)
            previous = {"revision": git_at(upstream, "rev-parse", "HEAD"), "branch": "main", "framework": "baseline-env", "node": "node"}
            cli.save_state(home, previous)
            private = home / "source/usr/private.txt"
            private.parent.mkdir()
            private.write_text("keep me")
            original_run = cli.run

            def prepare(*args, **kwargs):
                if args[0] == "git":
                    return original_run(*args, **kwargs)
                if "--check" in args:
                    self.assertEqual(cli.read_state(home), previous)
                    if fail:
                        raise RuntimeError("candidate rejected")

            for fail in (True, False):
                (upstream / "requirements.txt").write_text("# new revision\n" + str(fail))
                git_at(upstream, "add", ".")
                git_at(upstream, "commit", "-m", "update")
                with patch.object(cli, "UPSTREAM", str(upstream)), patch.object(cli.shutil, "which", return_value="tool"), patch.object(cli, "run", side_effect=prepare):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, "candidate rejected"):
                            cli.install(home, update=True)
                        self.assertEqual(cli.read_state(home), previous)
                        self.assertEqual(git_at(home / "source", "rev-parse", "HEAD"), previous["revision"])
                    else:
                        cli.install(home, update=True)
                        self.assertEqual(cli.read_state(home)["revision"], git_at(upstream, "rev-parse", "HEAD"))
                self.assertEqual(private.read_text(), "keep me")

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
