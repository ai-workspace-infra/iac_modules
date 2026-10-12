import json
import os
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

import helpers

SCRIPT = helpers.ROOT / "scripts/grafana-fallback-check.sh"


def serve(status, payload):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status if self.path == "/grafana/api/health" else 404)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class GrafanaFallbackTest(unittest.TestCase):
    def run_check(self, server, env=None):
        base = f"http://127.0.0.1:{server.server_port}/grafana"
        full_env = {"PATH": os.environ["PATH"], **(env or {})}  # no GUANCE_*/Vault variables at all
        result = subprocess.run(["bash", str(SCRIPT), "--url", base], capture_output=True, text=True, env=full_env, timeout=60)
        server.shutdown()
        server.server_close()
        return result

    def test_healthy_grafana_passes_without_any_guance_configuration(self):
        result = self.run_check(serve(200, {"database": "ok", "version": "13.2.3"}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("13.2.3", result.stdout)

    def test_unhealthy_database_fails(self):
        self.assertEqual(self.run_check(serve(200, {"database": "failing"})).returncode, 1)

    def test_http_error_and_garbage_fail(self):
        self.assertEqual(self.run_check(serve(503, {"database": "ok"})).returncode, 1)
        self.assertEqual(self.run_check(serve(200, b"<html>")).returncode, 1)

    def test_script_does_not_reference_guance_or_vault(self):
        text = "\n".join(line for line in SCRIPT.read_text().lower().splitlines() if not line.lstrip().startswith("#"))
        for word in ("guance_", "vault", "tf_var", "terraform"):
            self.assertNotIn(word, text)

    def test_url_validation(self):
        result = subprocess.run(["bash", str(SCRIPT), "--url", "file:///etc/passwd"], capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
