"""Exercise the real HTTP server and agent loop with a deterministic local provider.

Run only against a disposable installation. No paid provider or user credentials
are used. The fixture emits tool calls; upstream executes and persists them.
"""
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from http.client import RemoteDisconnected
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import build_opener, HTTPCookieProcessor, Request
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from oh_my_agent_zero.cli import adapter_command, default_home, environment, read_state


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    home = default_home()
    state = read_state(home)
    data = home / "source/usr"
    presets = data / "plugins/_model_config/presets.yaml"
    if presets.exists() or (data / ".env").exists() and "API_KEY_" in (data / ".env").read_text():
        raise RuntimeError("Use a fresh disposable installation: smoke tests must not replace your provider settings.")
    workdir = data / "workdir"
    steps = [
        ("code_execution_tool", {"runtime": "python", "code": "from pathlib import Path; Path('python-check.txt').write_text('42'); print('PYTHON_OK')"}),
        ("code_execution_tool", {"runtime": "nodejs", "code": "require('fs').writeFileSync('node-check.txt', String(await Promise.resolve(42))); console.log('NODE_OK')"}),
        ("code_execution_tool", {"runtime": "terminal", "code": "Set-Content -NoNewline terminal-check.txt 42; Write-Output 'TERMINAL_OK'" if os.name == "nt" else "printf 42 > terminal-check.txt; printf 'TERMINAL_OK\\n'"}),
        ("text_editor", {"action": "write", "path": str(workdir / "editor-check.txt"), "content": "original"}),
        ("text_editor", {"action": "patch", "path": str(workdir / "editor-check.txt"), "old_text": "original", "new_text": "patched"}),
        ("text_editor", {"action": "read", "path": str(workdir / "editor-check.txt")}),
        ("browser", {"action": "open", "url": "data:text/html,<h1>NATIVE_BROWSER_TOOL_OK</h1>", "include_content": True}),
        ("browser", {"action": "close_all"}),
        ("response", {"text": "NATIVE_SMOKE_COMPLETE"}),
    ]
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith("/embeddings"):
                inputs = body["input"]
                count = len(inputs) if isinstance(inputs, list) else 1
                result = {"object": "list", "data": [{"object": "embedding", "index": i, "embedding": [0.1] * 384} for i in range(count)], "model": "native-embedding", "usage": {"prompt_tokens": 1, "total_tokens": 1}}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                return
            if body["model"] == "native-main":
                index = len(calls)
                assert index < len(steps), "Agent unexpectedly retried/completed another turn"
                tool, args = steps[index]
                calls.append(tool)
                content = json.dumps({"thoughts": ["Run the deterministic native runtime check."], "headline": f"Native check {index}", "tool_name": tool, "tool_args": args})
            else:
                content = "Native smoke test"
            self.send_response(200)
            if body.get("stream"):
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                event = {"id": "native-test", "object": "chat.completion.chunk", "created": int(time.time()), "model": body["model"], "choices": [{"index": 0, "delta": {"role": "assistant", "content": content}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                event["choices"] = [{"index": 0, "delta": {}, "finish_reason": "stop"}]
                self.wfile.write(("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode())
            else:
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": "native-test", "object": "chat.completion", "created": int(time.time()), "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}).encode())

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{provider.server_port}/v1"
    preset = {"name": "Default"}
    for slot, model in (("chat", "native-main"), ("utility", "native-utility"), ("embedding", "native-embedding")):
        preset[slot] = {"provider": "openai", "name": model, "api_base": endpoint, "ctx_length": 100000, "kwargs": {"a0_api_mode": "chat_completions"} if slot != "embedding" else {}}
    presets.parent.mkdir(parents=True, exist_ok=True)
    presets.write_text(json.dumps([preset]), encoding="utf-8")
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    env = environment(home, state)
    env["API_KEY_OPENAI"] = "native-fixture-key"
    env["A0_SET_update_check_enabled"] = "false"
    server = None
    log = (home / "smoke.log").open("w", encoding="utf-8")

    def start():
        return subprocess.Popen([sys.executable, "-m", "oh_my_agent_zero", "--home", str(home), "start", "--port", str(port)], env=env,
                                cwd=Path(__file__).resolve().parents[1],
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=os.name != "nt")

    def stop():
        if server is not None and server.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(server.pid), "/T", "/F"], check=False, capture_output=True)
            else:
                os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

    def client():
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        token = None
        for _ in range(360):
            if server.poll() is not None:
                raise RuntimeError(f"Server exited; inspect {home / 'smoke.log'}")
            try:
                req = Request(base + "/api/csrf_token", headers={"Origin": base})
                result = json.load(opener.open(req, timeout=2))
                token = result["token"]
                break
            except (URLError, TimeoutError, KeyError):
                time.sleep(0.5)
        assert token, "Server did not become ready"

        def api(path, data=None):
            request = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                              headers={"Origin": base, "X-CSRF-Token": token, "Content-Type": "application/json"})
            return json.load(opener.open(request, timeout=180))
        return opener, api, result["runtime_id"]

    try:
        server = start()
        opener, api, runtime_id = client()
        assert b"Agent Zero" in opener.open(base).read()
        try:
            opener.open(Request(base + "/api/message", data=b'{}', headers={"Content-Type": "application/json"}))
            raise AssertionError("Missing CSRF token was accepted")
        except HTTPError as exc:
            assert exc.code == 403
        message = api("/api/message", {"text": "native-smoke-run: execute the native tool checks.", "context": ""})
        assert "NATIVE_SMOKE_COMPLETE" in message["message"], message
        context = message["context"]
        for name in ("python", "node", "terminal"):
            assert (workdir / f"{name}-check.txt").read_text().strip() == "42", name
        assert (workdir / "editor-check.txt").read_text() == "patched"
        assert len(calls) == len(steps), calls
        listing = api("/api/get_work_dir_files?path=" + quote(str(workdir)))
        assert "editor-check.txt" in json.dumps(listing), listing
        assert str(home / "source") in json.dumps(api("/api/get_work_dir_files"))
        snapshot = api("/api/poll", {"context": context})
        assert "NATIVE_SMOKE_COMPLETE" in json.dumps(snapshot)
        assert "NATIVE_BROWSER_TOOL_OK" in json.dumps(snapshot)
        for _ in range(30):
            if any((data / "chats").glob(f"{context}/*.json")):
                break
            time.sleep(1)
        try:
            api("/api/restart", {})
        except (RemoteDisconnected, URLError):
            pass
        _, api, restarted_id = client()
        assert runtime_id != restarted_id, "UI restart did not replace the framework process"
        snapshot = api("/api/poll", {"context": context})
        assert "NATIVE_SMOKE_COMPLETE" in json.dumps(snapshot), "Chat did not survive restart"
        assert (workdir / "editor-check.txt").read_text() == "patched"
        print("PASS: HTTP, CSRF rejection, full agent/tool loop, Python, Node, terminal, editor write/patch/read, browser tool, file browser, chat persistence, restart.")
    except BaseException:
        log.flush()
        print((home / "smoke.log").read_text(encoding="utf-8", errors="replace")[-24000:])
        raise
    finally:
        stop()
        provider.shutdown()
        log.close()
        presets.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
