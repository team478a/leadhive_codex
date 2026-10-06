"""Typed observation-only diagnostics. Never infer a reason from website/error text."""

import transport

CODES = frozenset(
    {
        "OBSERVATION_FAILED",
        "CANCELLED",
        "LAB_DISABLED",
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
    }
)


class ObservationFailure(transport.TransportBlocked):
    def __init__(self, code: str):
        if code not in CODES:
            code = "OBSERVATION_FAILED"
        self.code = code
        super().__init__(code)


def caused_by(error: BaseException, kind: type[BaseException]) -> bool:
    # Only inspect exception types in a bounded chain, never their string content.
    for _ in range(8):
        if isinstance(error, kind):
            return True
        if error.__context__ is None:
            return False
        error = error.__context__
    return False
