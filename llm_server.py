"""Small HTTP service that emulates an edge or cloud LLM endpoint."""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_LATENCY_MS = {"small": 35.0, "medium": 75.0, "large": 150.0}
REASONING_LATENCY_MS = {0: 0.0, 1: 20.0, 2: 55.0, 3: 95.0}


class ServerState:
    def __init__(self, name, inference_ms):
        self.name = name
        self.inference_ms = inference_ms
        self.active = 0
        self.completed = 0
        self.sessions = {}
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
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._send_json(400, {"error": "request body must be valid JSON"})
            return
        session_id = str(payload.get("session_id", "default"))
        model = str(payload.get("model", "small"))
        adapter = str(payload.get("adapter", "none"))
        reasoning_level = int(payload.get("reasoning_level", 0))
        state_action = str(payload.get("state_action", "local_reuse"))
        model_latency = MODEL_LATENCY_MS.get(model, self.state.inference_ms)
        reasoning_latency = REASONING_LATENCY_MS.get(reasoning_level, 0.0)
        inference_ms = self.state.inference_ms + model_latency + reasoning_latency
        with self.state.lock:
            self.state.active += 1
            previous = self.state.sessions.get(session_id)
            context_tokens = max(0, int(payload.get("context_tokens", 0)))
            kv_bytes = max(0, int(payload.get("kv_bytes", context_tokens * 4)))
            self.state.sessions[session_id] = {
                "model": model,
                "adapter": adapter,
                "context_tokens": context_tokens,
                "kv_bytes": kv_bytes,
            }
        started = time.perf_counter()
        try:
            time.sleep(inference_ms / 1000.0)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._send_json(200, {
                "backend": self.state.name,
                "response": "synthetic LLM response",
                "session_id": session_id,
                "model": model,
                "adapter": adapter,
                "reasoning_level": reasoning_level,
                "reasoning_tokens": {0: 0, 1: 128, 2: 512, 3: 1024}.get(reasoning_level, 0),
                "state_action": state_action,
                "state_reused": previous is not None and state_action == "local_reuse",
                "quality": round(min(1.0, {"small": 0.58, "medium": 0.76, "large": 0.91}.get(model, 0.5) +
                    {"none": 0.0, "networking": 0.10, "industrial": 0.12, "healthcare": 0.12}.get(adapter, 0.0) +
                    {0: 0.0, 1: 0.06, 2: 0.12, 3: 0.16}.get(reasoning_level, 0.0)), 3),
                "inference_ms": round(elapsed_ms, 2),
                "kv_bytes": kv_bytes,
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
