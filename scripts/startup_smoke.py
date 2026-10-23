"""First start of a fresh, disposable installation, through the installed launcher."""

import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oh_my_agent_zero.cli import default_home, read_state


def main():
    home = default_home()
    if (home / "state.json").exists() or (home / "source").exists():
        raise RuntimeError("Use a fresh disposable home; this test must exercise first start.")
    home.mkdir(parents=True, exist_ok=True)
    tools = Path(subprocess.check_output(["uv", "tool", "dir", "--bin"], text=True).strip())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    started = time.monotonic()
    with (home / "startup.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([str(tools / ("a0-native.exe" if os.name == "nt" else "a0-native")),
                                   "--home", str(home), "start", "--no-browser", "--port", str(port)],
                                  stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")
        try:
            while True:
                assert server.poll() is None, f"Launcher exited; see {home / 'startup.log'}"
                assert time.monotonic() - started < 15, "Progress page did not appear promptly"
                try:
                    with urlopen(base, timeout=2) as response:
                        assert response.headers.get("X-OMA0-Setup") == "1"
                        assert b"Preparing Agent Zero" in response.read()
                        break
                except (URLError, ConnectionError, TimeoutError):
                    time.sleep(0.1)
            assert not (home / "state.json").exists(), "Core was ready before the progress page"
            print(f"Progress page available after {time.monotonic() - started:.2f}s, before core setup completed.", flush=True)
            while True:
                assert server.poll() is None, f"Launcher exited; see {home / 'startup.log'}"
                assert time.monotonic() - started < 1200, "First start timed out"
                try:
                    with urlopen(Request(base, headers={"Accept": "application/json"}), timeout=2) as response:
                        if response.headers.get("X-OMA0-Setup") == "1":
                            status = json.load(response)
                            assert not status["failed"], f"Setup failed; see {home / 'startup.log'}"
                        else:
                            assert b"Agent Zero" in response.read()
                            break
                except (URLError, ConnectionError, TimeoutError):
                    pass
                time.sleep(0.5)
            with urlopen(Request(base + "/api/csrf_token", headers={"Origin": base}), timeout=10) as response:
                assert json.load(response)["token"], "Upstream CSRF endpoint did not become ready"
            state = read_state(home)
            assert not (home / state["framework"] / "native-features").exists()
            assert not (home / "browsers").exists()
            print("PASS: first-start setup handed the same address to the real upstream WebUI, with heavy features deferred.")
        except BaseException:
            log.flush()
            print((home / "startup.log").read_text(encoding="utf-8", errors="replace")[-16000:])
            raise
        finally:
            if server.poll() is None:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], check=False, capture_output=True)
                else:
                    os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    main()
