import json
import re

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

BUDGET_TOKENS_DEFAULT = 26000
LOOKBACK = 12  # look back further than the minimum 6 to be safe


class Step(BaseModel):
    step_number: int
    tool: str
    args: dict
    tokens_used: int


class BudgetRequest(BaseModel):
    budget_tokens: int = BUDGET_TOKENS_DEFAULT
    steps: list[Step]


_WS_RE = re.compile(r"\s+")


def _normalize_strings(obj):
    if isinstance(obj, str):
        return _WS_RE.sub(" ", obj).strip()
    if isinstance(obj, dict):
        return {k: _normalize_strings(v) for k, v in obj.items() if k != "request_id"}
    if isinstance(obj, list):
        return [_normalize_strings(v) for v in obj]
    return obj


def _canonical_args(args: dict) -> str:
    normalized = _normalize_strings(args)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _detect_loop(steps: list[Step]) -> str | None:
    if not steps:
        return None

    trail = steps[-LOOKBACK:]
    canon = [(s.tool, _canonical_args(s.args)) for s in trail]

    # Rule 1: same tool + identical canonical args, 3+ in a row (trailing run)
    run_len = 1
    for i in range(len(canon) - 2, -1, -1):
        if canon[i] == canon[-1]:
            run_len += 1
        else:
            break
    if run_len >= 3:
        return f"Same tool call ('{canon[-1][0]}') repeated identically {run_len} times in a row."

    # Rule 2: trailing 2-step cycle A,B,A,B,... for >=6 trailing steps
    if len(canon) >= 6:
        # find longest trailing alternating run with period 2
        cyc_len = 1
        for i in range(len(canon) - 2, -1, -1):
            # alternation means canon[i] should equal canon[i+2] pattern check;
            # simplest: compare position parity against the last two distinct values
            pass
        # direct check: take the last 6 (or more) and see if it strictly alternates A,B,A,B,...
        for window in range(len(canon), 5, -1):
            sub = canon[-window:]
            a, b = sub[0], sub[1] if len(sub) > 1 else sub[0]
            if a == b:
                continue
            if all(sub[i] == (a if i % 2 == 0 else b) for i in range(len(sub))) and window >= 6:
                return f"Trailing {window} steps show a repeating 2-step cycle with no progress."
    return None


@router.post("/budget-loop-guard")
def budget_loop_guard(req: BudgetRequest):
    total = sum(s.tokens_used for s in req.steps)

    if total >= req.budget_tokens:
        return {
            "decision": "halt",
            "reason": f"Cumulative tokens_used ({total}) has reached the budget ({req.budget_tokens}).",
        }

    loop_reason = _detect_loop(req.steps)
    if loop_reason:
        return {"decision": "halt", "reason": loop_reason}

    return {"decision": "continue", "reason": f"Under budget ({total}/{req.budget_tokens}) and no loop detected."}
