"""
W2 — Jaccard-Cosine Boundary Segmentation.

Online agglomerative clustering over the stream of PostToolUse(Edit|Write)
events. When a new event's distance to the active cluster exceeds threshold
theta, the cluster closes and a boundary fires.

Distance function (multi-modal):

    d(a, b) = alpha * (1 - jaccard(files_a, files_b))
            + beta  * (1 - cosine(vec_a, vec_b))
            + gamma * tanh((t_b - t_a) / tau)

Weights (alpha=0.4, beta=0.4, gamma=0.2, tau=300s) defaulted from
constants.sh; W5 tunes them per-developer later.

Vector extraction:
  - If Raven V1 embedding is available on the event, use it as vec.
  - Else (standalone mode), compute a stdlib vector from the edit content
    itself: the set of non-stopword tokens from the changed lines,
    L2-normalized as a dict-weighted bag-of-tokens.

Stdlib only. No numpy. No external deps.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Match shared/constants.sh values. Adjusted at runtime if W5 has tuned them.
DEFAULT_ALPHA = 0.4
DEFAULT_BETA = 0.4
DEFAULT_GAMMA = 0.2
DEFAULT_TAU_SECONDS = 300
DEFAULT_THRESHOLD = 0.55
DEFAULT_UNCERTAINTY_BAND = 0.10

# Tokenization: ASCII word-like runs, min length 2. Case-folded.
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")

# Tiny English stopword set — keeps the vector signal, not the noise.
_STOPWORDS = frozenset("""
the a an and or but not is are was were be been being have has had do
does did of to in for on with at by from up down out about
this that these those it its they them as if then else so such than
return if else for while break continue class def function const let var
import export from as new null true false none self this super
""".split())


# ──────────────────────────────────────────────────────────────────────
# Event + cluster data model
# ──────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    """One PostToolUse(Edit|Write) record, normalized."""
    timestamp: float
    tool: str              # "Edit" | "Write" | "MultiEdit"
    files: set[str]        # absolute or repo-relative paths touched
    vector: dict[str, float]  # L2-normalized token weights (sparse dict)
    raw: dict[str, Any] = field(default_factory=dict)  # full event for reference

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "files": sorted(self.files),
            "vector": self.vector,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Event":
        return cls(
            timestamp=float(d["timestamp"]),
            tool=str(d["tool"]),
            files=set(d.get("files", [])),
            vector=dict(d.get("vector", {})),
        )


@dataclass
class Cluster:
    """An open task-boundary cluster — events that belong together."""
    opened_at: float
    events: list[Event] = field(default_factory=list)

    @property
    def last_event(self) -> Event:
        return self.events[-1]

    @property
    def file_union(self) -> set[str]:
        u: set[str] = set()
        for e in self.events:
            u |= e.files
        return u

    @property
    def centroid_vector(self) -> dict[str, float]:
        """Average of member vectors, L2-normalized."""
        if not self.events:
            return {}
        acc: dict[str, float] = {}
        for e in self.events:
            for k, v in e.vector.items():
                acc[k] = acc.get(k, 0.0) + v
        n = len(self.events)
        acc = {k: v / n for k, v in acc.items()}
        return _l2_normalize(acc)

    def to_json(self) -> dict[str, Any]:
        return {
            "opened_at": self.opened_at,
            "events": [e.to_json() for e in self.events],
            "file_count": len(self.file_union),
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Cluster":
        return cls(
            opened_at=float(d["opened_at"]),
            events=[Event.from_json(e) for e in d.get("events", [])],
        )


# ──────────────────────────────────────────────────────────────────────
# Vector extraction from raw PostToolUse payload
# ──────────────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Extract lowercase identifier-like tokens, skipping stopwords + very short."""
    if not text:
        return []
    out: list[str] = []
    for m in _TOKEN_RE.finditer(text):
        t = m.group().lower()
        if t in _STOPWORDS:
            continue
        out.append(t)
    return out


def _l2_normalize(v: dict[str, float]) -> dict[str, float]:
    if not v:
        return {}
    norm = math.sqrt(sum(x * x for x in v.values()))
    if norm == 0:
        return {}
    return {k: x / norm for k, x in v.items()}


def vector_from_text(text: str) -> dict[str, float]:
    """Frequency-weighted, L2-normalized bag of identifier tokens."""
    counts: dict[str, float] = {}
    for t in tokenize(text):
        counts[t] = counts.get(t, 0.0) + 1.0
    return _l2_normalize(counts)


def event_from_post_tool_use(payload: dict[str, Any], v1_embedding: dict[str, float] | None = None) -> Event | None:
    """Normalize a Claude Code PostToolUse payload into an Event.

    Recognized tool_inputs:
      - Edit:       { file_path, old_string, new_string }
      - MultiEdit:  { file_path, edits: [{old_string, new_string}, ...] }
      - Write:      { file_path, content }

    Returns None if the payload isn't an Edit/Write/MultiEdit event.
    """
    tool = str(payload.get("tool_name") or payload.get("tool") or "")
    if tool not in ("Edit", "Write", "MultiEdit"):
        return None

    ti = payload.get("tool_input") or {}
    file_path = ti.get("file_path")
    if not file_path:
        return None

    # Collect the textual change for vectorization.
    text_chunks: list[str] = []
    if tool == "Edit":
        text_chunks.append(str(ti.get("new_string") or ""))
        text_chunks.append(str(ti.get("old_string") or ""))
    elif tool == "MultiEdit":
        for e in ti.get("edits") or []:
            text_chunks.append(str(e.get("new_string") or ""))
            text_chunks.append(str(e.get("old_string") or ""))
    elif tool == "Write":
        text_chunks.append(str(ti.get("content") or ""))

    text = "\n".join(text_chunks)

    # If Raven V1 embedding is attached, prefer it; else compute stdlib vector.
    vec = v1_embedding if v1_embedding else vector_from_text(text)

    return Event(
        timestamp=float(payload.get("timestamp") or time.time()),
        tool=tool,
        files={file_path},
        vector=vec,
        raw=payload,
    )


# ──────────────────────────────────────────────────────────────────────
# Distance function
# ──────────────────────────────────────────────────────────────────────

def jaccard(a: set[str], b: set[str]) -> float:
    """|a ∩ b| / |a ∪ b|; returns 1.0 when both empty (identical)."""
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 1.0


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity for sparse dict vectors (already L2-normalized)."""
    if not a or not b:
        return 0.0
    # Iterate over the smaller.
    if len(a) > len(b):
        a, b = b, a
    s = 0.0
    for k, v in a.items():
        s += v * b.get(k, 0.0)
    # Inputs are L2-normalized so dot-product == cosine.
    return max(-1.0, min(1.0, s))


@dataclass
class DistanceConfig:
    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    gamma: float = DEFAULT_GAMMA
    tau_seconds: float = DEFAULT_TAU_SECONDS


def distance(event: Event, cluster: Cluster, cfg: DistanceConfig | None = None) -> float:
    """Multi-modal distance: 0.0 = identical, 1.0 = orthogonal+file-disjoint+stale."""
    cfg = cfg or DistanceConfig()
    if not cluster.events:
        return 0.0

    file_d = 1.0 - jaccard(event.files, cluster.file_union)
    vec_d = 1.0 - cosine(event.vector, cluster.centroid_vector)
    dt = max(0.0, event.timestamp - cluster.last_event.timestamp)
    time_d = math.tanh(dt / max(1.0, cfg.tau_seconds))

    return (cfg.alpha * file_d) + (cfg.beta * vec_d) + (cfg.gamma * time_d)


# ──────────────────────────────────────────────────────────────────────
# Online segmenter — the core of W2
# ──────────────────────────────────────────────────────────────────────

@dataclass
class SegmentationResult:
    """One step of the online clustering: did a boundary fire, is it uncertain?"""
    boundary_fired: bool
    uncertain: bool               # distance within theta ± uncertainty_band
    distance: float
    closed_cluster: Cluster | None
    active_cluster: Cluster


@dataclass
class Segmenter:
    """Stateful online agglomerative clustering.

    Call step(event) on each PostToolUse(Edit|Write) event. Persist state
    via to_json() / from_json() across SessionStart + PreCompact.
    """
    threshold: float = DEFAULT_THRESHOLD
    uncertainty_band: float = DEFAULT_UNCERTAINTY_BAND
    cfg: DistanceConfig = field(default_factory=DistanceConfig)
    active: Cluster | None = None
    closed_clusters: list[Cluster] = field(default_factory=list)

    def step(self, event: Event) -> SegmentationResult:
        """Process one event. Returns whether a boundary fired."""
        if self.active is None:
            self.active = Cluster(opened_at=event.timestamp, events=[event])
            return SegmentationResult(
                boundary_fired=False,
                uncertain=False,
                distance=0.0,
                closed_cluster=None,
                active_cluster=self.active,
            )

        d = distance(event, self.active, self.cfg)

        if d > self.threshold:
            # Close the active cluster, open a new one with this event.
            closed = self.active
            self.closed_clusters.append(closed)
            self.active = Cluster(opened_at=event.timestamp, events=[event])
            uncertain = abs(d - self.threshold) <= self.uncertainty_band
            return SegmentationResult(
                boundary_fired=True,
                uncertain=uncertain,
                distance=d,
                closed_cluster=closed,
                active_cluster=self.active,
            )

        # Below threshold → append to active.
        self.active.events.append(event)
        uncertain = abs(d - self.threshold) <= self.uncertainty_band
        return SegmentationResult(
            boundary_fired=False,
            uncertain=uncertain,
            distance=d,
            closed_cluster=None,
            active_cluster=self.active,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            "uncertainty_band": self.uncertainty_band,
            "cfg": {
                "alpha": self.cfg.alpha,
                "beta": self.cfg.beta,
                "gamma": self.cfg.gamma,
                "tau_seconds": self.cfg.tau_seconds,
            },
            "active": self.active.to_json() if self.active else None,
            "closed_clusters": [c.to_json() for c in self.closed_clusters[-20:]],
            # Keep only the last 20 closed clusters to cap state growth.
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Segmenter":
        cfg_d = d.get("cfg", {})
        cfg = DistanceConfig(
            alpha=float(cfg_d.get("alpha", DEFAULT_ALPHA)),
            beta=float(cfg_d.get("beta", DEFAULT_BETA)),
            gamma=float(cfg_d.get("gamma", DEFAULT_GAMMA)),
            tau_seconds=float(cfg_d.get("tau_seconds", DEFAULT_TAU_SECONDS)),
        )
        active = Cluster.from_json(d["active"]) if d.get("active") else None
        closed = [Cluster.from_json(c) for c in d.get("closed_clusters", [])]
        return cls(
            threshold=float(d.get("threshold", DEFAULT_THRESHOLD)),
            uncertainty_band=float(d.get("uncertainty_band", DEFAULT_UNCERTAINTY_BAND)),
            cfg=cfg,
            active=active,
            closed_clusters=closed,
        )


# ──────────────────────────────────────────────────────────────────────
# CLI — consumed by the PostToolUse hook
# ──────────────────────────────────────────────────────────────────────

def _load_state(state_path: Path) -> Segmenter:
    if state_path.exists():
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                return Segmenter.from_json(json.load(f))
        except Exception:
            # Corrupted state → start fresh; the previous cluster is lost but
            # session continues. Audit via stderr only.
            print(f"[boundary-segmenter] state corrupted, starting fresh: {state_path}", file=sys.stderr)
    return Segmenter()


def _save_state(state_path: Path, seg: Segmenter) -> None:
    # Atomic write via tempfile + rename (Fae A4 pattern inline — avoids
    # importing atomic_json from a subprocess context where sys.path may not
    # yet be set).
    import tempfile
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(state_path.parent),
        prefix=f".{state_path.name}.", suffix=".tmp", delete=False,
    ) as tmp:
        json.dump(seg.to_json(), tmp, indent=2)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, state_path)


def __main_cli():
    """CLI for the PostToolUse hook.

    Reads the Claude Code hook payload from stdin, loads cluster state,
    steps once, persists state, and emits a JSON verdict on stdout:

        {"boundary": true|false, "uncertain": true|false, "distance": <float>,
         "closed_cluster": {...}|null, "active_cluster": {...}}

    Arg 1 is the state file path (required — the hook passes it so we don't
    have to hardcode the plugin's state/).
    """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: boundary_segment.py <state-file>"}))
        sys.exit(3)

    state_path = Path(sys.argv[1])

    payload_raw = sys.stdin.read()
    if not payload_raw.strip():
        print(json.dumps({"boundary": False, "skipped": "empty-payload"}))
        sys.exit(0)

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"boundary": False, "skipped": f"invalid-json: {exc}"}))
        sys.exit(0)

    event = event_from_post_tool_use(payload)
    if event is None:
        # Not an Edit/Write/MultiEdit — nothing to segment.
        print(json.dumps({"boundary": False, "skipped": "not-edit-tool"}))
        sys.exit(0)

    seg = _load_state(state_path)
    result = seg.step(event)
    _save_state(state_path, seg)

    # Confidence is a monotonic inversion of the observed distance clamped to
    # [0.0, 1.0]. Callers (the PostToolUse hook, the Opus escalation path)
    # treat confidence < SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD as a signal to
    # route the decision to the boundary-detector agent rather than acting
    # autonomously. Keep the raw `distance` field as well for back-compat.
    confidence = max(0.0, min(1.0, 1.0 - result.distance))

    out: dict[str, Any] = {
        "boundary": result.boundary_fired,
        "uncertain": result.uncertain,
        "distance": round(result.distance, 4),
        "confidence": round(confidence, 4),
        "active_cluster": result.active_cluster.to_json(),
    }
    if result.closed_cluster:
        out["closed_cluster"] = result.closed_cluster.to_json()

    print(json.dumps(out, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    __main_cli()
