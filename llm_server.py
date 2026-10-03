"""Small HTTP service that emulates an edge or cloud LLM endpoint."""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ServerState:
    def __init__(self, name, inference_ms):
        self.name = name
        self.inference_ms = inference_ms
        self.active = 0
        self.completed = 0
        self.lock = threading.Lock()


class LLMHandler(BaseHTTPRequestHandler):
    state = None

    def log_message(self, format_string, *args):
        return

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            with self.state.lock:
                payload = {"backend": self.state.name, "active": self.state.active, "completed": self.state.completed}
            self._send_json(200, payload)
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/generate":
            self._send_json(404, {"error": "not found"})
            return
        with self.state.lock:
            self.state.active += 1
        started = time.perf_counter()
        try:
            time.sleep(self.state.inference_ms / 1000.0)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._send_json(200, {
                "backend": self.state.name,
                "response": "synthetic LLM response",
                "inference_ms": round(elapsed_ms, 2),
            })
        finally:
            with self.state.lock:
                self.state.active -= 1
                self.state.completed += 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True, choices=("edge", "cloud"))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--inference-ms", type=float, required=True)
    args = parser.parse_args()
    LLMHandler.state = ServerState(args.name, args.inference_ms)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), LLMHandler)
    print(json.dumps({"status": "ready", "backend": args.name, "port": args.port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
