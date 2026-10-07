from typing import Literal, cast

from pydantic import Field

from app.schema_core import Input

Platform = Literal[
    "INSTAGRAM",
    "X",
    "FACEBOOK",
    "YOUTUBE",
    "TIKTOK",
    "HOTPEPPER",
    "HOTPEPPER_BEAUTY",
    "TABELOG",
    "GURUNAVI",
    "EPARK",
    "RAKUTEN_BEAUTY",
    "INDEED",
    "KYUJIN_BOX",
]


class PresenceSearchPlan(Input):
    modes: dict[Platform, Literal["AUTO", "SEARCH", "REQUIRED"]] = Field(default_factory=dict)
    required_platforms: list[Platform] = Field(default_factory=list, max_length=13)
    max_extra_searches: int = Field(default=5, ge=0, le=30)
    timeout_seconds: int = Field(default=60, ge=5, le=300)

    def mode(self, platform: str) -> str:
        if platform in self.required_platforms:
            return "REQUIRED"
        return self.modes.get(cast(Platform, platform), "AUTO")
