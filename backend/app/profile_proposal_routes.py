from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import current_user
from app.services.ai import AiAnalysisError
from app.services.application_settings import apply_application_settings
from app.services.scraper import ScrapeError
from app.services.target_profile_proposal import ProposalInput, ProposalOutput, propose

router = APIRouter(prefix="/api/target-profiles")


@router.post("/propose-from-url", response_model=ProposalOutput)
def propose_from_url(
    body: ProposalInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    apply_application_settings(db)
    try:
        return propose(body)
    except (AiAnalysisError, ScrapeError) as exc:
        raise HTTPException(422, exc.public_message) from None
