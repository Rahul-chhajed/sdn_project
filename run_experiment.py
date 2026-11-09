"""Run static-cloud and dynamic SDN steering phases and write CSV metrics."""
import argparse
import csv
import json
import os
import shlex
import time
import urllib.request

from mininet.log import info, setLogLevel

from topology import build_network, start_llm_services

CONTROLLER_API = "http://127.0.0.1:8080"
SERVICE_URL = "http://10.0.0.50:8000/generate"


def post_json(url, payload):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def set_policy(mode, backend=None):
    payload = {"mode": mode}
    if backend:
        payload["backend"] = backend
    return post_json(f"{CONTROLLER_API}/policy", payload)


def run_phase(client, client_script, phase, count, pause_ms, prompt, orchestrate=False):
    results = []
    session_id = f"experiment-{phase}"
    for index in range(count):
        decision = {
            "model": "large" if phase == "static_cloud" else "small",
            "adapter": "none",
            "reasoning_level": 0,
            "state_action": "local_reuse",
            "context_tokens": index * 256,
            "kv_bytes": index * 1024,
        }
        if orchestrate:
            decision = post_json(f"{CONTROLLER_API}/orchestrate", {
                "session_id": session_id,
                "task": "networking",
                "complexity": "normal",
                "quality_min": 0.70,
                "deadline_ms": 500,
                "context_tokens": index * 256,
                "kv_bytes": index * 1024,
            })
        decision.setdefault("context_tokens", index * 256)
        decision.setdefault("kv_bytes", index * 1024)
        options = " ".join(
            f"--{name.replace('_', '-')} {shlex.quote(str(decision[name]))}"
            for name in (
                "model", "adapter", "reasoning_level", "state_action",
                "context_tokens", "kv_bytes",
            )
        )
        command = (
            f"python3 {shlex.quote(client_script)} --requests 1 --pause-ms 0 "
            f"--session-id {shlex.quote(session_id)} --prompt {shlex.quote(prompt)} {options}"
        )
        output = client.cmd(command)
        for line in output.splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row["phase"] = phase
            for name in ("model", "adapter", "reasoning_level", "reasoning_tokens", "state_action", "quality"):
                if name in decision:
                    row[f"selected_{name}"] = decision[name]
            results.append(row)
            if orchestrate:
                post_json(f"{CONTROLLER_API}/complete", {
                    "session_id": session_id,
                    "backend": row.get("backend", decision.get("backend", "edge")),
                    "context_tokens": (index + 1) * 256,
                    "kv_bytes": row.get("kv_bytes", (index + 1) * 1024),
                })
        time.sleep(pause_ms / 1000.0)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--pause-ms", type=float, default=100)
    parser.add_argument("--output", default="results.csv")
    parser.add_argument("--prompt", default="benchmark request")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    args = parser.parse_args()
    setLogLevel("warning")
    net = build_network(args.controller_ip, args.controller_port)
    try:
        client, edge, cloud = net["client"], net["edge"], net["cloud"]
        server_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm_server.py")
        client_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client.py")
        start_llm_services(net)

        set_policy("static", "cloud")
        rows = run_phase(client, client_path, "static_cloud", args.requests, args.pause_ms, args.prompt)
        set_policy("dynamic")
        rows.extend(run_phase(client, client_path, "dynamic", args.requests, args.pause_ms, args.prompt, orchestrate=True))

        with open(args.output, "w", newline="", encoding="utf-8") as output:
            fields = [
                "phase", "request", "backend", "model", "adapter", "reasoning_level",
                "reasoning_tokens", "state_action", "quality", "inference_ms", "end_to_end_ms",
            ]
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader()
            writer.writerows({field: row.get(field, "") for field in fields} for row in rows)
        print_summary(rows)
        info("Results written to %s\n" % args.output)
    finally:
        net.stop()


def print_summary(rows):
    for phase in ("static_cloud", "dynamic"):
        phase_rows = [row for row in rows if row.get("phase") == phase]
        if not phase_rows:
            continue
        mean_e2e = sum(float(row["end_to_end_ms"]) for row in phase_rows) / len(phase_rows)
        mean_inference = sum(float(row["inference_ms"]) for row in phase_rows) / len(phase_rows)
        counts = {}
        for row in phase_rows:
            counts[row["backend"]] = counts.get(row["backend"], 0) + 1
        print(json.dumps({
            "phase": phase,
            "requests": len(phase_rows),
            "mean_end_to_end_ms": round(mean_e2e, 2),
            "mean_inference_ms": round(mean_inference, 2),
            "backend_counts": counts,
        }))


if __name__ == "__main__":
    main()
