"""Human administrator configuration for daily sending hours."""

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.model_settings import SendingWindow
from app.models import User
from app.schema_core import Input
from app.security import current_admin
from app.services.sending_window import allowed

router = APIRouter(prefix="/api/admin/sending-window")


class WindowInput(Input):
    enabled: bool
    start_minute: int = Field(default=480, ge=0, le=1439)
    end_minute: int = Field(default=1200, ge=1, le=1439)

    @model_validator(mode="after")
    def ordered(self):
        if self.start_minute >= self.end_minute:
            raise ValueError("終了時刻は開始時刻より後にしてください。")
        return self


def output(db):
    saved = db.get(SendingWindow, 1)
    return {
        "enabled": saved.enabled if saved else False,
        "start_minute": saved.start_minute if saved else 480,
        "end_minute": saved.end_minute if saved else 1200,
        "timezone": "Asia/Tokyo",
        "allowed_now": allowed(db),
    }


@router.get("")
def read(db: Session = Depends(get_db), user: User = Depends(current_admin)):
    return output(db)


@router.put("")
def update(
    body: WindowInput,
    db: Session = Depends(get_db),
    user: User = Depends(current_admin),
):
    saved = db.get(SendingWindow, 1)
    if saved is None:
        saved = SendingWindow(id=1)
        db.add(saved)
    for key, value in body.model_dump().items():
        setattr(saved, key, value)
    saved.updated_by_user_id = user.id
    db.commit()
    return output(db)
