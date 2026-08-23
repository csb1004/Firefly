from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import require_ready_user
from ..services.set_catalog import user_set_definitions


router = APIRouter(prefix="/api/sets", tags=["sets"])


@router.get("")
def list_user_sets(
    user: User = Depends(require_ready_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return user_set_definitions(db, user.id)
