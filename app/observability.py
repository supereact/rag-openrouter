"""Small, tenant-scoped in-memory metrics for the local RAG development server.

No prompts, document text, user names, API keys, or raw request URLs are recorded.
Metrics are per process and intentionally reset at restart. For multi-worker
production environments, replace this with a real metrics/tracing backend.
"""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import math
import os
from threading import Lock
from time import perf_counter
from typing import Iterator, Mapping, Any

MAX_TENANTS = 1000
MAX_SAMPLES = 256
ALLOWED_PHASES = frozenset({
    ("search", "retrieval"),
    ("ask", "retrieval"),
    ("ask", "generation"),
})


@dataclass
class _Counters:
    calls: int = 0
    errors: int = 0
    total_ms: float = 0.0
    samples: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_SAMPLES))
    prompt_tokens: int = 0
    completion_tokens: int = 0
    provider_cost_credits: float = 0.0
    provider_cost_samples: int = 0
    usage_samples: int = 0


_lock = Lock()
_metrics: dict[int, dict[tuple[str, str], _Counters]] = {}
_last_usage: ContextVar[dict[str, float | int] | None] = ContextVar(
    "rag_last_llm_usage", default=None
)


def _is_enabled() -> bool:
    return os.getenv("RAG_OBSERVABILITY_ENABLED", "true").strip().lower() not in (
        "false", "0", "no", "off"
    )


def _record(tenant_id: int, operation: str, phase: str, ms: float, success: bool) -> None:
    if not _is_enabled() or (operation, phase) not in ALLOWED_PHASES:
        return
    if not isinstance(ms, (float, int)) or not math.isfinite(ms) or ms < 0:
        return
    with _lock:
        if tenant_id not in _metrics and len(_metrics) >= MAX_TENANTS:
            # Observability must never prevent requests from completing.
            return
        counter = _metrics.setdefault(tenant_id, {}).setdefault((operation, phase), _Counters())
        counter.calls += 1
        counter.errors += int(not success)
        counter.total_ms += float(ms)
        counter.samples.append(float(ms))


@contextmanager
def measure(tenant_id: int, operation: str, phase: str) -> Iterator[None]:
    start = perf_counter()
    try:
        yield
    except BaseException:
        _record(tenant_id, operation, phase, (perf_counter() - start) * 1000, False)
        raise
    else:
        _record(tenant_id, operation, phase, (perf_counter() - start) * 1000, True)


def _field(value: object, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _tokens(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or int(value) != value:
        return None
    return int(value)


def _cost(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def reset_llm_usage() -> None:
    """Reset per-request provider usage before generation in the same worker thread."""
    _last_usage.set(None)


def capture_llm_usage(usage: object, *, provider: str) -> None:
    """Read only aggregate accounting; never store raw provider responses.

    OpenRouter's `cost` is billed account credits, not a client-side estimate.
    Cost from other providers is intentionally not inferred.
    """
    if usage is None:
        return
    raw_prompt = _field(usage, "prompt_tokens")
    raw_completion = _field(usage, "completion_tokens")
    if provider == "openai":
        raw_prompt = _field(usage, "input_tokens")
        raw_completion = _field(usage, "output_tokens")
    prompt = _tokens(raw_prompt)
    completion = _tokens(raw_completion)
    cost = _cost(_field(usage, "cost")) if provider == "openrouter" else None
    if prompt is None and completion is None and cost is None:
        return
    data: dict[str, int | float] = {}
    if prompt is not None:
        data["prompt_tokens"] = prompt
    if completion is not None:
        data["completion_tokens"] = completion
    if cost is not None:
        data["provider_cost_credits"] = cost
    _last_usage.set(data)


def peek_llm_usage() -> dict[str, float | int] | None:
    """Read aggregate usage before save_request_usage consumes the context."""
    data = _last_usage.get()
    return dict(data) if data is not None else None


def save_request_usage(tenant_id: int) -> None:
    """Add usage to the already-measured ask/generation row, if provided."""
    usage = _last_usage.get()
    _last_usage.set(None)
    if usage is None or not _is_enabled():
        return
    with _lock:
        row = _metrics.get(tenant_id, {}).get(("ask", "generation"))
        if row is None:
            return
        row.usage_samples += 1
        row.prompt_tokens += int(usage.get("prompt_tokens", 0))
        row.completion_tokens += int(usage.get("completion_tokens", 0))
        if "provider_cost_credits" in usage:
            row.provider_cost_credits += float(usage["provider_cost_credits"])
            row.provider_cost_samples += 1


def _percentile(samples: deque[float], p: float) -> float | None:
    if not samples:
        return None
    values = sorted(samples)
    # Nearest-rank percentile, meaningful for small bounded samples.
    idx = max(0, min(len(values) - 1, math.ceil(p * len(values)) - 1))
    return round(values[idx], 2)


def snapshot(tenant_id: int) -> dict:
    """Return isolated counters for the authenticated admin's own tenant."""
    with _lock:
        rows = []
        for (operation, phase), c in sorted(_metrics.get(tenant_id, {}).items()):
            rows.append({
                "operation": operation,
                "phase": phase,
                "calls": c.calls,
                "errors": c.errors,
                "error_rate": round(c.errors / c.calls, 4) if c.calls else 0.0,
                "average_ms": round(c.total_ms / c.calls, 2) if c.calls else None,
                "p50_ms": _percentile(c.samples, 0.50),
                "p95_ms": _percentile(c.samples, 0.95),
                "latency_sample_count": len(c.samples),
                "prompt_tokens": c.prompt_tokens,
                "completion_tokens": c.completion_tokens,
                "usage_samples": c.usage_samples,
                "provider_cost_credits": round(c.provider_cost_credits, 8),
                "provider_cost_samples": c.provider_cost_samples,
            })
    return {
        "enabled": _is_enabled(),
        "scope": "current_tenant_current_process",
        "window": "since_process_start",
        "max_latency_samples_per_phase": MAX_SAMPLES,
        "metrics": rows,
    }
