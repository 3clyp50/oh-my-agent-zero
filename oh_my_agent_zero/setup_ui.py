"""Temporary first-start progress page; the real UI belongs to upstream."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
import webbrowser


PAGE = b"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent Zero setup</title>
<style>
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; }
main { max-width: 36rem; padding: 2rem; line-height: 1.6; }
h1 { line-height: 1.2; }
progress { width: 100%; }
.hint { opacity: .7; }
</style>
<main>
<h1>Preparing Agent Zero</h1>
<p>The first start downloads the core runtime. Keep this terminal open.
The Agent Zero WebUI will open here automatically when ready.</p>
<progress aria-label="Preparing the core runtime"></progress>
<p id="stage" role="status" aria-live="polite">Starting setup...</p>
<p class="hint">Full download details appear in the terminal. Speech, Chromium,
and advanced document features are prepared when you first use them.</p>
</main>
<script>
async function refresh() {
    try {
        const response = await fetch('/', {cache: 'no-store', headers: {Accept: 'application/json'}});
        if (response.ok && response.headers.get('X-OMA0-Setup') !== '1') {
            location.reload();
            return;
        }
        if (response.ok) {
            const status = await response.json();
            document.querySelector('#stage').textContent = status.stage;
            if (status.failed) {
                document.querySelector('h1').textContent = 'Setup needs attention';
                document.querySelector('progress').hidden = true;
            }
        }
    } catch (_) {} // The progress server closes while upstream starts on this port.
    setTimeout(refresh, 1000);
}
refresh();
</script>
</html>
"""


@contextmanager
def setup_page(port, open_browser=True):
    status = {"stage": "Starting setup...", "failed": False}
    url = f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if (self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}"
                    or self.headers.get("Origin", url) != url
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                self.send_error(403)
                return
            if self.path != "/":
                self.send_error(404)
                return
            is_json = self.headers.get("Accept") == "application/json"
            body = json.dumps(status).encode() if is_json else PAGE
            self.send_response(200)
            self.send_header("Content-Type", "application/json" if is_json else "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-OMA0-Setup", "1")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; "
                             "style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

    class Server(ThreadingHTTPServer):
        # Windows SO_REUSEADDR can take a port already owned by another server.
        allow_reuse_address = os.name != "nt"

    with Server(("127.0.0.1", port), Handler) as server:
        worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        worker.start()
        print(f"First-start setup: {url}\nCtrl+C stops setup; rerun 'a0-native start' to retry.", flush=True)
        if open_browser:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        try:
            yield lambda message: status.update(stage=message)
        except Exception as exc:
            status.update(stage="Setup failed. See the terminal for details. Press Ctrl+C there, then rerun a0-native start to retry.", failed=True)
            print(f"Setup failed: {exc}\nPress Ctrl+C, then rerun 'a0-native start' to retry.", flush=True)
            try:
                while True:
                    time.sleep(0.5)
            except KeyboardInterrupt:
                raise exc
        finally:
            server.shutdown()
            worker.join()
