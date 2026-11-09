"""Summarize experiment.csv with paper-style latency and orchestration metrics."""
import argparse
import csv
import json
import statistics
from collections import Counter


def number(row, field, default=0.0):
    value = row.get(field, "")
    return float(value) if value not in (None, "") else default


def percentile(values, percentile):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def summarize(rows, deadline_ms):
    end_to_end = [number(row, "end_to_end_ms") for row in rows]
    inference = [number(row, "inference_ms") for row in rows]
    qualities = [number(row, "quality") for row in rows if row.get("quality", "") != ""]
    reasoning = [number(row, "reasoning_tokens") for row in rows if row.get("reasoning_tokens", "") != ""]
    return {
        "requests": len(rows),
        "backend_counts": dict(Counter(row.get("backend", "unknown") for row in rows)),
        "model_counts": dict(Counter(row.get("model", "unknown") for row in rows)),
        "state_action_counts": dict(Counter(row.get("state_action", "unknown") for row in rows)),
        "mean_end_to_end_ms": round(statistics.mean(end_to_end), 2) if end_to_end else 0.0,
        "std_end_to_end_ms": round(statistics.stdev(end_to_end), 2) if len(end_to_end) > 1 else 0.0,
        "p95_end_to_end_ms": round(percentile(end_to_end, 0.95), 2),
        "mean_inference_ms": round(statistics.mean(inference), 2) if inference else 0.0,
        "sla_violation_rate": round(sum(value > deadline_ms for value in end_to_end) / len(end_to_end), 4) if end_to_end else 0.0,
        "mean_quality": round(statistics.mean(qualities), 3) if qualities else 0.0,
        "mean_reasoning_tokens": round(statistics.mean(reasoning), 2) if reasoning else 0.0,
    }


def main():
    parser = argparse.ArgumentParser(description="Summarize SDN LLM experiment results")
    parser.add_argument("--input", default="results.csv")
    parser.add_argument("--deadline-ms", type=float, default=500.0)
    args = parser.parse_args()

    with open(args.input, newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    phases = {}
    for phase in sorted({row.get("phase", "unknown") for row in rows}):
        phases[phase] = summarize([row for row in rows if row.get("phase") == phase], args.deadline_ms)

    report = {"input": args.input, "deadline_ms": args.deadline_ms, "phases": phases}
    static = phases.get("static_cloud")
    dynamic = phases.get("dynamic")
    if static and dynamic and static["mean_end_to_end_ms"]:
        report["dynamic_latency_reduction_percent"] = round(
            100.0 * (static["mean_end_to_end_ms"] - dynamic["mean_end_to_end_ms"])
            / static["mean_end_to_end_ms"],
            2,
        )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
