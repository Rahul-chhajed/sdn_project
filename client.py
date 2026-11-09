"""Generate requests from a Mininet host and print one JSON result per request."""
import argparse
import json
import time
import urllib.request


def request(url, payload):
    body = json.dumps(payload).encode("utf-8")
    started = time.perf_counter()
    with urllib.request.urlopen(urllib.request.Request(url, data=body, method="POST"), timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    result["end_to_end_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://10.0.0.50:8000/generate")
    parser.add_argument("--requests", type=int, default=10)
    parser.add_argument("--pause-ms", type=float, default=100)
    parser.add_argument("--prompt", default="benchmark request")
    parser.add_argument("--session-id", default="default")
    parser.add_argument("--task", default="general")
    parser.add_argument("--complexity", default="normal")
    parser.add_argument("--privacy", choices=("standard", "sensitive"), default="standard")
    parser.add_argument("--quality-min", type=float, default=0.60)
    parser.add_argument("--deadline-ms", type=float, default=500.0)
    parser.add_argument("--context-tokens", type=int, default=0)
    parser.add_argument("--kv-bytes", type=int, default=0)
    parser.add_argument("--model", default="small")
    parser.add_argument("--adapter", default="none")
    parser.add_argument("--reasoning-level", type=int, choices=(0, 1, 2, 3), default=0)
    parser.add_argument("--state-action", default="local_reuse")
    args = parser.parse_args()
    for index in range(args.requests):
        payload = {
            "prompt": args.prompt,
            "session_id": args.session_id,
            "task": args.task,
            "complexity": args.complexity,
            "privacy": args.privacy,
            "quality_min": args.quality_min,
            "deadline_ms": args.deadline_ms,
            "context_tokens": args.context_tokens,
            "kv_bytes": args.kv_bytes,
            "model": args.model,
            "adapter": args.adapter,
            "reasoning_level": args.reasoning_level,
            "state_action": args.state_action,
        }
        print(json.dumps({"request": index + 1, **request(args.url, payload)}), flush=True)
        time.sleep(args.pause_ms / 1000.0)


if __name__ == "__main__":
    main()
