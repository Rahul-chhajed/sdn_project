"""Request-level model, state, and reasoning orchestration for the prototype."""
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelProfile:
    name: str
    quality: float
    inference_ms: float
    memory_gb: float
    cost: float


@dataclass(frozen=True)
class AdapterProfile:
    name: str
    quality_bonus: float
    memory_gb: float


@dataclass
class SessionState:
    backend: str
    context_tokens: int
    kv_bytes: int


MODELS = {
    "small": ModelProfile("small", quality=0.58, inference_ms=35.0, memory_gb=4.0, cost=0.2),
    "medium": ModelProfile("medium", quality=0.76, inference_ms=75.0, memory_gb=10.0, cost=0.5),
    "large": ModelProfile("large", quality=0.91, inference_ms=150.0, memory_gb=24.0, cost=1.2),
}

ADAPTERS = {
    "none": AdapterProfile("none", quality_bonus=0.0, memory_gb=0.0),
    "networking": AdapterProfile("networking", quality_bonus=0.10, memory_gb=1.0),
    "industrial": AdapterProfile("industrial", quality_bonus=0.12, memory_gb=1.5),
    "healthcare": AdapterProfile("healthcare", quality_bonus=0.12, memory_gb=1.5),
}

REASONING = {
    0: {"tokens": 0, "quality_bonus": 0.00, "latency_ms": 0.0, "cost": 0.0},
    1: {"tokens": 128, "quality_bonus": 0.06, "latency_ms": 20.0, "cost": 0.1},
    2: {"tokens": 512, "quality_bonus": 0.12, "latency_ms": 55.0, "cost": 0.3},
    3: {"tokens": 1024, "quality_bonus": 0.16, "latency_ms": 95.0, "cost": 0.6},
}


class OrchestrationError(ValueError):
    """Raised when no configuration can satisfy a request."""


class Orchestrator:
    def __init__(self, backends: Dict[str, dict]):
        self.backends = backends
        self.sessions: Dict[str, SessionState] = {}

    def decide(self, request: dict) -> dict:
        session_id = str(request.get("session_id", "default"))
        complexity = str(request.get("complexity", "normal"))
        privacy = str(request.get("privacy", "standard"))
        quality_min = float(request.get("quality_min", 0.60))
        deadline_ms = float(request.get("deadline_ms", 500.0))
        adapter_name = self._adapter_for(request)
        candidates = []

        for backend_name, backend in self.backends.items():
            if privacy == "sensitive" and not backend.get("private", False):
                continue
            for model_name, model in MODELS.items():
                if model_name not in backend.get("models", []):
                    continue
                if model.memory_gb > backend.get("memory_gb", 0.0):
                    continue
                if adapter_name not in backend.get("adapters", []):
                    continue
                adapter = ADAPTERS[adapter_name]
                for reasoning_level, reasoning in REASONING.items():
                    quality = min(1.0, model.quality + adapter.quality_bonus + reasoning["quality_bonus"])
                    if quality < quality_min:
                        continue
                    state_action, state_ms = self._state_plan(session_id, backend_name, request, model)
                    inference_ms = model.inference_ms + reasoning["latency_ms"]
                    estimated_ms = backend.get("latency_ms", 0.0) + inference_ms + state_ms
                    if estimated_ms > deadline_ms:
                        continue
                    score = (
                        estimated_ms
                        + backend.get("load", 0.0) * 80.0
                        + model.cost * 20.0
                        + reasoning["cost"] * 15.0
                        + state_ms * 0.25
                    )
                    candidates.append({
                        "backend": backend_name,
                        "model": model_name,
                        "adapter": adapter_name,
                        "reasoning_level": reasoning_level,
                        "reasoning_tokens": reasoning["tokens"],
                        "state_action": state_action,
                        "quality": round(quality, 3),
                        "estimated_latency_ms": round(estimated_ms, 2),
                        "estimated_state_ms": round(state_ms, 2),
                        "score": round(score, 2),
                    })

        if not candidates:
            raise OrchestrationError(
                "no feasible configuration for privacy, quality, memory, or deadline constraints"
            )
        decision = min(candidates, key=lambda candidate: candidate["score"])
        self.sessions[session_id] = SessionState(
            backend=decision["backend"],
            context_tokens=max(0, int(request.get("context_tokens", 0))),
            kv_bytes=max(0, int(request.get("kv_bytes", 0))),
        )
        decision["session_id"] = session_id
        decision["candidate_count"] = len(candidates)
        return decision

    def complete(self, payload: dict) -> dict:
        session_id = str(payload.get("session_id", "default"))
        state = self.sessions.get(session_id)
        if state is None:
            state = SessionState(
                backend=str(payload.get("backend", "edge")),
                context_tokens=0,
                kv_bytes=0,
            )
            self.sessions[session_id] = state
        state.backend = str(payload.get("backend", state.backend))
        state.context_tokens = max(0, int(payload.get("context_tokens", state.context_tokens)))
        state.kv_bytes = max(0, int(payload.get("kv_bytes", state.kv_bytes)))
        return {
            "session_id": session_id,
            "backend": state.backend,
            "context_tokens": state.context_tokens,
            "kv_bytes": state.kv_bytes,
        }

    def snapshot(self) -> dict:
        return {
            session_id: {
                "backend": state.backend,
                "context_tokens": state.context_tokens,
                "kv_bytes": state.kv_bytes,
            }
            for session_id, state in self.sessions.items()
        }

    def _adapter_for(self, request: dict) -> str:
        requested = request.get("adapter")
        if requested is not None and str(requested) in ADAPTERS:
            return str(requested)
        task = str(request.get("task", "general"))
        return {
            "networking": "networking",
            "industrial": "industrial",
            "healthcare": "healthcare",
        }.get(task, "none")

    def _state_plan(self, session_id: str, backend_name: str, request: dict, model: ModelProfile):
        previous = self.sessions.get(session_id)
        if previous is None or previous.backend == backend_name:
            return "local_reuse", 0.0
        kv_bytes = max(previous.kv_bytes, int(request.get("kv_bytes", 0)))
        throughput = max(1.0, float(self.backends[backend_name].get("state_bandwidth_mbps", 100.0)))
        migration_ms = 8.0 + (kv_bytes * 8.0 / (throughput * 1000.0))
        recompute_ms = max(5.0, previous.context_tokens * model.inference_ms / 1000.0)
        if migration_ms <= recompute_ms:
            return "kv_migrate", migration_ms
        return "context_recompute", recompute_ms
