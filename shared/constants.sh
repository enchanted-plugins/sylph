#!/usr/bin/env bash
# Sylph shared constants — sourced by all hooks and utilities

SYLPH_VERSION="0.0.1"

# ── State file names (relative to each plugin's state/ dir) ────────────────
SYLPH_AUDIT_FILE="state/audit.jsonl"                   # sylph-gate destructive-op log
SYLPH_METRICS_FILE="state/metrics.jsonl"               # per-plugin metrics (sibling convention)
SYLPH_BOUNDARY_CLUSTERS_FILE="state/boundary-clusters.json"  # W2 cluster state
SYLPH_WORKFLOW_MAP_FILE="state/workflow-map.json"      # W3 per-subtree workflow labels
SYLPH_LEARNINGS_FILE="state/learnings.json"            # W5 Gauss Accumulation persistence
SYLPH_CAPABILITY_REGISTRY_FILE="state/capability-registry.json"  # provider capability baseline
SYLPH_SESSION_CACHE_DIR="state/session-cache"          # per-session probe results (24h TTL)

# ── Size limits ────────────────────────────────────────────────────────────
SYLPH_MAX_AUDIT_BYTES=10485760         # 10MB — rotate at this size
SYLPH_MAX_METRICS_BYTES=10485760       # 10MB
SYLPH_MAX_CLUSTERS_BYTES=2097152       # 2MB — clustering state is small
SYLPH_MAX_LEARNINGS_BYTES=524288       # 512KB — moving averages only

# ── Boundary-segmentation (W2) thresholds ──────────────────────────────────
# Jaccard-Cosine Boundary Segmentation distance weights.
SYLPH_BOUNDARY_ALPHA="0.4"             # Jaccard weight
SYLPH_BOUNDARY_BETA="0.4"              # Crow V1 cosine weight
SYLPH_BOUNDARY_GAMMA="0.2"             # Idle-gap tanh weight
SYLPH_BOUNDARY_TAU_SECONDS=300         # Idle-gap scale factor
SYLPH_BOUNDARY_THRESHOLD="0.55"        # Cluster-close threshold
SYLPH_BOUNDARY_UNCERTAINTY="0.10"      # +/- band that routes to Opus judgment
SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD="${SYLPH_BOUNDARY_CONFIDENCE_THRESHOLD:-0.7}"  # Boundary confidence floor; below this, escalate to Opus boundary-detector

# ── Commit-classifier (W1) thresholds ──────────────────────────────────────
SYLPH_COMMIT_SUBJECT_MAX=72
SYLPH_COMMIT_BODY_LINE_MAX=72
SYLPH_COMMIT_DIFF_COMPRESS_TOKENS=1500  # Above this, substitute Crow V1

# ── Capability-registry runtime probing ────────────────────────────────────
SYLPH_PROBE_CACHE_TTL_SECONDS=86400    # 24h cache
SYLPH_PROBE_TIMEOUT_SECONDS=3          # Network probe hard limit

# ── Reviewer routing (W4) ──────────────────────────────────────────────────
SYLPH_REVIEWER_MAX_SUGGEST=3            # Cap auto-assigned reviewers (avoid Kubernetes-style storms)
SYLPH_REVIEWER_RECENCY_HALF_LIFE_DAYS=90

# ── Destructive-op recovery windows (informational, shown in gate prompt) ──
SYLPH_RECOVERY_REFLOG_DAYS=90
SYLPH_RECOVERY_REMOTE_DEFAULT_DAYS=14   # GitHub default; host-specific via capability-registry

# ── Gauss Learning (W5) ────────────────────────────────────────────────────
SYLPH_GAUSS_ALPHA="0.3"                # EMA learning rate
SYLPH_GAUSS_BOOTSTRAP_MIN_SAMPLES=10    # Below this, use priors only

# ── Lock config (atomic mkdir pattern shared with siblings) ────────────────
SYLPH_LOCK_SUFFIX=".lock"
SYLPH_LOCK_STALE_SECONDS=60

# ── Session cache prefix ───────────────────────────────────────────────────
SYLPH_CACHE_PREFIX="/tmp/sylph-"
