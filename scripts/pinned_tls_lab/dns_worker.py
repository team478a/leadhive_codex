"""Trusted stdlib-only, one-shot DNS child. No application imports or credentials."""

import json
import socket
import sys


def lookup(host: str) -> bytes:
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not 0 < len(answers) <= 64:
        raise ValueError("DNS answer bounds")
    addresses = []
    for answer in answers:
        address = answer[4][0]
        if not isinstance(address, str) or len(address) > 64:
            raise ValueError("DNS address bounds")
        if address not in addresses:
            addresses.append(address)
    return json.dumps({"version": 1, "addresses": addresses}, ensure_ascii=True).encode(
        "ascii"
    )


def main() -> int:
    try:
        if len(sys.argv) != 2:
            return 2
        sys.stdout.buffer.write(lookup(sys.argv[1]))
        return 0
    except (OSError, ValueError):
        return 2


if __name__ == "__main__":
    sys.exit(main())
