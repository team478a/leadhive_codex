"""Closed, non-secret diagnostics shared by managed observation paths."""

from typing import Literal, get_args

Reason = Literal[
    "QUEUED",
    "CLAIMED",
    "CANCELLED",
    "EVIDENCE_SAVED",
    "CLAIM_REJECTED",
    "OBSERVATION_FAILED",
    "BINDING_CHANGED",
    "LEASE_CHANGED",
    "WORKER_LOST",
    "PERMISSION_CHANGED",
    "SOURCE_CHANGED",
    "LAB_DISABLED",
    "RUNNER_STOPPED",
    "OBSERVATION_TIMEOUT",
    "OBSERVATION_DNS_FAILED",
    "OBSERVATION_UNSAFE_DNS",
    "OBSERVATION_TLS_FAILED",
    "OBSERVATION_NETWORK_FAILED",
    "OBSERVATION_HTTP_REJECTED",
    "OBSERVATION_RESPONSE_INVALID",
    "OBSERVATION_ROBOTS_DENIED",
    "OBSERVATION_ROBOTS_INVALID",
    "OBSERVATION_PARSE_FAILED",
    "OBSERVATION_CONTRACT_INVALID",
    "OBSERVATION_STORAGE_FAILED",
]
REASONS = frozenset(get_args(Reason))
REASON_CONSTRAINT = (
    "reason_code IN (" + ",".join("'" + code + "'" for code in get_args(Reason)) + ")"
)
