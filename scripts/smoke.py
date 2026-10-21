"""Exercise the real HTTP server and agent loop with a deterministic local provider.

Run only against a disposable installation. No paid provider or user credentials
are used. The fixture emits tool calls; upstream executes and persists them.
"""
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
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
from oh_my_agent_zero.native import native_path


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connector", action="store_true", help="Also test the installed a0 CLI against this disposable server")
    args = parser.parse_args()
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
        ("code_execution_tool", {"runtime": "terminal", "code": "Set-Content -LiteralPath 'terminal-check.txt' -Value '42' -NoNewline; Get-Item -LiteralPath 'terminal-check.txt' | Select-Object FullName,Length; Write-Output ('TERMINAL_' + 'OK')" if os.name == "nt" else "printf 42 > terminal-check.txt; printf 'TERMINAL_%s\\n' OK"}),
        ("text_editor", {"action": "write", "path": str(workdir / "editor-check.txt"), "content": "original"}),
        ("text_editor", {"action": "patch", "path": str(workdir / "editor-check.txt"), "old_text": "original", "new_text": "patched"}),
        ("text_editor", {"action": "read", "path": str(workdir / "editor-check.txt")}),
        ("browser", {"action": "open", "url": "data:text/html,<h1>NATIVE_BROWSER_TOOL_OK</h1>", "include_content": True}),
        ("browser", {"action": "evaluate", "script": "document.querySelector('h1').textContent"}),
        ("browser", {"action": "close_all"}),
        ("search_engine", {"query": "native fixture"}),
        ("response", {"text": "NATIVE_SMOKE_COMPLETE"}),
    ]
    initial_step_count = len(steps)
    steps.extend([
        ("text_editor", {"action": "read", "path": str(data / "uploads/native-upload.txt")}),
        ("response", {"text": "NATIVE_ATTACHMENT_COMPLETE"}),
    ])
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/search":
                assert b"q=native+fixture" in raw
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"results": [{"title": "NATIVE_SEARCH_OK", "url": "https://example.com", "content": "Local search fixture"}]}).encode())
                return
            body = json.loads(raw)
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
                print(f"Fixture turn {index + 1}: {tool}", flush=True)
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
    env["OMA0_SEARXNG_URL"] = f"http://127.0.0.1:{provider.server_port}/search"
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
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Server exited; inspect {home / 'smoke.log'}")
            try:
                req = Request(base + "/api/csrf_token", headers={"Origin": base})
                result = json.load(opener.open(req, timeout=2))
                token = result["token"]
                break
            except (URLError, ConnectionError, TimeoutError, KeyError):
                time.sleep(0.5)
        assert token, "Server did not become ready"

        def api(path, data=None, content_type="application/json"):
            payload = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
            request = Request(base + path, data=payload,
                              headers={"Origin": base, "X-CSRF-Token": token, "Content-Type": content_type})
            return json.load(opener.open(request, timeout=180))
        return opener, api, result["runtime_id"]

    try:
        print("Starting native server and waiting for authenticated HTTP readiness...", flush=True)
        server = start()
        opener, api, runtime_id = client()
        print("WebUI ready; checking CSRF and dispatching real agent tools...", flush=True)
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
            proof = workdir / f"{name}-check.txt"
            assert proof.exists(), f"Missing {name} proof; files: {[p.name for p in workdir.iterdir()]}"
            assert proof.read_text().strip() == "42", name
        assert (workdir / "editor-check.txt").read_text() == "patched"
        assert len(calls) == initial_step_count, calls
        listing = api("/api/get_work_dir_files?path=" + quote(str(workdir)))
        assert "editor-check.txt" in json.dumps(listing), listing
        assert Path(native_path(api("/api/get_work_dir_files")["data"]["current_path"], home / "source")) == home / "source"
        snapshot = api("/api/poll", {"context": context})
        assert "NATIVE_SMOKE_COMPLETE" in json.dumps(snapshot)
        assert "NATIVE_BROWSER_TOOL_OK" in json.dumps(snapshot)
        assert "NATIVE_SEARCH_OK" in json.dumps(snapshot)
        assert "TERMINAL_OK" in json.dumps(snapshot), "Terminal command did not finish"
        boundary = "native-smoke-boundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\nRead the attached file.\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="context"\r\n\r\n{context}\r\n'
                f'--{boundary}\r\nContent-Disposition: form-data; name="attachments"; filename="native-upload.txt"\r\n'
                f'Content-Type: text/plain\r\n\r\nNATIVE_UPLOAD_OK\r\n--{boundary}--\r\n').encode()
        attached = api("/api/message", body, f"multipart/form-data; boundary={boundary}")
        assert "NATIVE_ATTACHMENT_COMPLETE" in attached["message"]
        assert (data / "uploads/native-upload.txt").read_text() == "NATIVE_UPLOAD_OK"
        assert len(calls) == len(steps)
        for content in ("first", "replacement"):
            upload = (f'--{boundary}\r\nContent-Disposition: form-data; name="path"\r\n\r\n{workdir}\r\n'
                      f'--{boundary}\r\nContent-Disposition: form-data; name="files[]"; filename="transfer-proof.txt"\r\n'
                      f'Content-Type: text/plain\r\n\r\n{content}\r\n--{boundary}--\r\n').encode()
            receipt = api("/api/upload_work_dir_files", upload, f"multipart/form-data; boundary={boundary}")
            assert receipt.get("successful") == ["transfer-proof.txt"], receipt
            assert (workdir / "transfer-proof.txt").read_text() == content
        history = api("/api/plugins/_time_travel/history_snapshot", {"context_id": context, "message": "Native snapshot"})
        assert history["ok"] and history["snapshot"]["hash"], history
        snapshot_hash = history["snapshot"]["hash"]
        for _ in range(30):
            if any((data / "chats").glob(f"{context}/*.json")):
                break
            time.sleep(1)
        try:
            api("/api/restart", {})
        except (ConnectionError, URLError):
            pass
        _, api, restarted_id = client()
        assert runtime_id != restarted_id, "UI restart did not replace the framework process"
        snapshot = api("/api/poll", {"context": context})
        assert "NATIVE_SMOKE_COMPLETE" in json.dumps(snapshot), "Chat did not survive restart"
        assert (workdir / "editor-check.txt").read_text() == "patched"
        history = api("/api/plugins/_time_travel/history_list", {"context_id": context})
        assert snapshot_hash in json.dumps(history), history
        if args.connector:
            steps.append(("response", {"text": "NATIVE_CONNECTOR_COMPLETE"}))
            tool_bin = Path(subprocess.check_output(["uv", "tool", "dir", "--bin"], text=True).strip())
            connector = subprocess.run(
                [str(tool_bin / ("a0.exe" if os.name == "nt" else "a0")), "headless", "--host", base,
                 "--no-docker-discovery", "--chat", context, "--workspace", str(workdir),
                 "--print", "native-connector-smoke: verify the native connection.", "--output", "jsonl"],
                capture_output=True, text=True, encoding="utf-8", timeout=120,
            )
            assert connector.returncode == 0, connector.stdout + connector.stderr
            assert "NATIVE_CONNECTOR_COMPLETE" in connector.stdout, connector.stdout + connector.stderr
            assert len(calls) == len(steps), calls
            print("PASS: installed a0-connector connected to the native server and completed a chat.")
        print("PASS: HTTP, CSRF rejection, full agent/tool loop, Python, Node, terminal, editor write/patch/read, browser tool, search routing, attachments, file transfers, file browser, Time Travel snapshots, chat persistence, UI restart.")
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
