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
    args = parser.parse_args()
    for index in range(args.requests):
        print(json.dumps({"request": index + 1, **request(args.url, {"prompt": args.prompt})}), flush=True)
        time.sleep(args.pause_ms / 1000.0)


if __name__ == "__main__":
    main()
