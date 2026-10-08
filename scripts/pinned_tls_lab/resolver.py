"""Isolated DNS deadline prototype, with bounded admission and owned-child cleanup."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

SLOTS = threading.BoundedSemaphore(4)
FAULT = threading.Event()
FAILED_CHILDREN: list[subprocess.Popen[bytes]] = []
CLEANUP_SECONDS = 1.0


class ResolutionFailure(ValueError):
    pass


class ResolutionTimeout(ResolutionFailure):
    pass


class ResolutionCleanupFailure(ResolutionFailure):
    """Must block further execution; OS termination was not confirmed."""


def worker_command(host: str) -> list[str]:
    return [
        sys.executable,
        "-I",
        str(Path(__file__).with_name("dns_worker.py").resolve()),
        host,
    ]


def decode(output: bytes) -> tuple[str, ...]:
    if not output or len(output) > 8192:
        raise ResolutionFailure("Invalid DNS result")

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ResolutionFailure("Invalid DNS result")
            result[key] = value
        return result

    try:
        value = json.loads(output, object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        raise ResolutionFailure("Invalid DNS result") from None
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "addresses"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not isinstance(value["addresses"], list)
        or not 0 < len(value["addresses"]) <= 64
        or any(
            not isinstance(ip, str) or not 0 < len(ip) <= 64 or "%" in ip
            for ip in value["addresses"]
        )
    ):
        raise ResolutionFailure("Invalid DNS result")
    return tuple(dict.fromkeys(value["addresses"]))


def isolated_resolve(host: str, timeout: float = 5) -> tuple[str, ...]:
    if os.environ.get("PINNED_TLS_LAB") != "1":
        raise ResolutionFailure("Resolver lab is disabled")
    if FAULT.is_set():
        raise ResolutionCleanupFailure("DNS resolver quarantined")
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ResolutionFailure("Invalid DNS timeout")
    if not re.fullmatch(r"[a-z0-9.-]{1,253}", host) or any(
        not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
        for part in host.split(".")
    ):
        raise ResolutionFailure("Invalid DNS hostname")
    deadline = time.monotonic() + timeout
    if not SLOTS.acquire(timeout=timeout):
        raise ResolutionTimeout("DNS admission timeout")
    process: subprocess.Popen[bytes] | None = None
    try:
        if FAULT.is_set():
            raise ResolutionCleanupFailure("DNS resolver quarantined")
        if time.monotonic() >= deadline:
            raise ResolutionTimeout("DNS deadline exceeded")
        # Do not inherit database/API/SMTP keys, proxy settings, PYTHONPATH or user config.
        child_env = {
            k: v
            for k, v in os.environ.items()
            if k.upper() in {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP"}
        }
        try:
            process = subprocess.Popen(
                worker_command(host),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                env=child_env,
                cwd=Path(__file__).parent,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ResolutionTimeout("DNS deadline exceeded")
            output, _ = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired:
            raise ResolutionTimeout("DNS deadline exceeded") from None
        except OSError:
            raise ResolutionFailure("DNS process failed") from None
        if process.returncode != 0:
            raise ResolutionFailure("DNS resolution failed")
        if time.monotonic() >= deadline:
            raise ResolutionTimeout("DNS deadline exceeded")
        return decode(output)
    finally:
        try:
            if process is not None:
                terminated = False
                try:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=CLEANUP_SECONDS)
                    terminated = True
                except (OSError, subprocess.TimeoutExpired):
                    FAULT.set()
                    FAILED_CHILDREN.append(process)
                    raise ResolutionCleanupFailure(
                        "DNS termination unconfirmed"
                    ) from None
                finally:
                    # Closing a pipe while a Windows reader still blocks can itself hang.
                    # Quarantine retains the owned handle for operator investigation.
                    if terminated and process.stdout is not None:
                        process.stdout.close()
        finally:
            SLOTS.release()
