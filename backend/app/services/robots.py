"""Shared robots.txt parsing rules without network-client dependencies."""

import urllib.robotparser
from urllib.parse import urlsplit, urlunsplit


def robots_parser(robots_text: str, robots_url: str) -> urllib.robotparser.RobotFileParser:
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(robots_text.splitlines())
    return parser


def robots_can_fetch(robots_text: str, url: str, user_agent: str) -> bool:
    parsed_url = urlsplit(url)
    robots_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, "/robots.txt", "", ""))
    return robots_parser(robots_text, robots_url).can_fetch(user_agent, url)
