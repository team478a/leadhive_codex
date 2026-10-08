"""Allowlisted lab runtimes only; never a production compatibility registry."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    version: str
    commit: str
    archive_sha256: str
    wp_image: str


PROFILES = {
    "6.1.4": Profile(
        "6.1.4",
        "165278e868387ec393569ecd2dbfda37e8b5b950",
        "7cfdd76cfa25ffd7a2f3c1cb245dd5be1ede8989a5347ade2fa8a839d943b5f1",
        "wordpress:6.8.3-php8.3-apache",
    ),
    "6.2": Profile(
        "6.2",
        "34acb3a6995b403274820c5ea42abd01b754c03b",
        "be61bf5bd0f99187e7f15b285b1bf1590038105e2b267501b81003066c93d1cb",
        "wordpress:7.1.2-php8.3-apache",
    ),
}


def get_profile(name: str) -> Profile:
    if name not in PROFILES:
        raise ValueError("Unknown lab runtime profile")
    return PROFILES[name]
