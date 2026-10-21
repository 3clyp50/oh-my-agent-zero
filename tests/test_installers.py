import os
from pathlib import Path
import subprocess
import tempfile
import unittest


@unittest.skipIf(os.name == "nt", "Unix bootstrap; Windows bootstrap runs in platform CI")
class InstallerTests(unittest.TestCase):
    def test_bundle_install_and_failure_boundaries(self):
        installer = Path(__file__).resolve().parents[1] / "scripts/install.sh"
        for failure in (None, "PACKAGE_EXIT", "NATIVE_EXIT", "DOWNLOAD_EXIT", "CONNECTOR_EXIT"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                tools = root / "tools with spaces"
                tools.mkdir()
                scripts = {
                    "git": "exit 0\n",
                    "uv": '''if [ "$*" = 'tool dir --bin' ]; then
    printf '%s\\n' "$TEST_TOOLS"
else
    [ "$#" -eq 5 ] && [ "$5" = "$OMA0_PACKAGE_SPEC" ] || exit 9
    echo launcher >> "$TEST_LOG"
    exit "${PACKAGE_EXIT:-0}"
fi
''',
                    "a0-native": 'echo native >> "$TEST_LOG"\nexit "${NATIVE_EXIT:-0}"\n',
                    "a0": 'echo version >> "$TEST_LOG"\necho "a0 2.14"\n',
                    "curl": '''[ "$2" = 'https://raw.githubusercontent.com/agent0ai/a0-connector/main/install.sh' ] || exit 9
echo download >> "$TEST_LOG"
[ "${DOWNLOAD_EXIT:-0}" = 0 ] || exit "$DOWNLOAD_EXIT"
cp "$TEST_CONNECTOR" "$4"
''',
                }
                for name, body in scripts.items():
                    path = tools / name
                    path.write_text("#!/bin/sh\n" + body)
                    path.chmod(0o755)
                connector = root / "connector.sh"
                connector.write_text('echo connector >> "$TEST_LOG"\nexit "${CONNECTOR_EXIT:-0}"\n')
                log = root / "calls.log"
                env = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                       "TMPDIR": str(root), "TEST_TOOLS": str(tools), "TEST_LOG": str(log),
                       "TEST_CONNECTOR": str(connector), "OMA0_PACKAGE_SPEC": str(root / "local package")}
                if failure:
                    env[failure] = "7"
                result = subprocess.run(["sh", str(installer)], env=env, text=True, capture_output=True)
                expected = ["launcher", "native", "download", "connector", "version"]
                if failure:
                    expected = expected[:{"PACKAGE_EXIT": 1, "NATIVE_EXIT": 2,
                                          "DOWNLOAD_EXIT": 3, "CONNECTOR_EXIT": 4}[failure]]
                self.assertEqual(log.read_text().splitlines(), expected)
                self.assertEqual(result.returncode, 7 if failure else 0, result.stderr)
                self.assertEqual("Both Agent Zero and a0-connector are installed." in result.stdout, failure is None)
                self.assertEqual({p.name for p in root.iterdir()}, {"tools with spaces", "connector.sh", "calls.log"})
                if not failure:
                    self.assertIn('--host http://127.0.0.1:50001 --connect --no-docker-discovery', result.stdout)


if __name__ == "__main__":
    unittest.main()
