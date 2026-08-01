from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ProrationRequest(BaseModel):
    old_price: float
    new_price: float
    days_remaining: float
    days_in_actual_month: float
    spec: str


@router.post("/proration")
def proration(req: ProrationRequest):
    diff = req.new_price - req.old_price
    if req.spec == "v1":
        charge = diff * (req.days_remaining / 30)
    elif req.spec == "v2":
        charge = diff * (req.days_remaining / req.days_in_actual_month)
    else:
        # Unknown spec: fail loud rather than silently guessing.
        return {"charge": None, "error": f"unknown spec '{req.spec}'"}
    return {"charge": round(charge, 10)}
