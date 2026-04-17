#!/usr/bin/env bash
# Weaver shared constants — sourced by all hooks and utilities

WEAVER_VERSION="0.0.1"

# ── State file names (relative to each plugin's state/ dir) ────────────────
WEAVER_AUDIT_FILE="state/audit.jsonl"                   # weaver-gate destructive-op log
WEAVER_METRICS_FILE="state/metrics.jsonl"               # per-plugin metrics (sibling convention)
WEAVER_BOUNDARY_CLUSTERS_FILE="state/boundary-clusters.json"  # W2 cluster state
WEAVER_WORKFLOW_MAP_FILE="state/workflow-map.json"      # W3 per-subtree workflow labels
WEAVER_LEARNINGS_FILE="state/learnings.json"            # W5 Gauss Accumulation persistence
WEAVER_CAPABILITY_REGISTRY_FILE="state/capability-registry.json"  # provider capability baseline
WEAVER_SESSION_CACHE_DIR="state/session-cache"          # per-session probe results (24h TTL)

# ── Size limits ────────────────────────────────────────────────────────────
WEAVER_MAX_AUDIT_BYTES=10485760         # 10MB — rotate at this size
WEAVER_MAX_METRICS_BYTES=10485760       # 10MB
WEAVER_MAX_CLUSTERS_BYTES=2097152       # 2MB — clustering state is small
WEAVER_MAX_LEARNINGS_BYTES=524288       # 512KB — moving averages only

# ── Boundary-segmentation (W2) thresholds ──────────────────────────────────
# Jaccard-Cosine Boundary Segmentation distance weights.
WEAVER_BOUNDARY_ALPHA="0.4"             # Jaccard weight
WEAVER_BOUNDARY_BETA="0.4"              # Hornet V1 cosine weight
WEAVER_BOUNDARY_GAMMA="0.2"             # Idle-gap tanh weight
WEAVER_BOUNDARY_TAU_SECONDS=300         # Idle-gap scale factor
WEAVER_BOUNDARY_THRESHOLD="0.55"        # Cluster-close threshold
WEAVER_BOUNDARY_UNCERTAINTY="0.10"      # +/- band that routes to Opus judgment

# ── Commit-classifier (W1) thresholds ──────────────────────────────────────
WEAVER_COMMIT_SUBJECT_MAX=72
WEAVER_COMMIT_BODY_LINE_MAX=72
WEAVER_COMMIT_DIFF_COMPRESS_TOKENS=1500  # Above this, substitute Hornet V1

# ── Capability-registry runtime probing ────────────────────────────────────
WEAVER_PROBE_CACHE_TTL_SECONDS=86400    # 24h cache
WEAVER_PROBE_TIMEOUT_SECONDS=3          # Network probe hard limit

# ── Reviewer routing (W4) ──────────────────────────────────────────────────
WEAVER_REVIEWER_MAX_SUGGEST=3            # Cap auto-assigned reviewers (avoid Kubernetes-style storms)
WEAVER_REVIEWER_RECENCY_HALF_LIFE_DAYS=90

# ── Destructive-op recovery windows (informational, shown in gate prompt) ──
WEAVER_RECOVERY_REFLOG_DAYS=90
WEAVER_RECOVERY_REMOTE_DEFAULT_DAYS=14   # GitHub default; host-specific via capability-registry

# ── Gauss Learning (W5) ────────────────────────────────────────────────────
WEAVER_GAUSS_ALPHA="0.3"                # EMA learning rate
WEAVER_GAUSS_BOOTSTRAP_MIN_SAMPLES=10    # Below this, use priors only

# ── Lock config (atomic mkdir pattern shared with siblings) ────────────────
WEAVER_LOCK_SUFFIX=".lock"
WEAVER_LOCK_STALE_SECONDS=60

# ── Session cache prefix ───────────────────────────────────────────────────
WEAVER_CACHE_PREFIX="/tmp/weaver-"
