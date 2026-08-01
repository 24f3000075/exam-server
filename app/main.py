from fastapi import FastAPI

from . import proration, redteam_guardrail, agent_guardrail, skill_scanner, budget_loop, mcp_server

app = FastAPI(title="exam-server")

app.include_router(proration.router)
app.include_router(redteam_guardrail.router)
app.include_router(agent_guardrail.router)
app.include_router(skill_scanner.router)
app.include_router(budget_loop.router)
app.include_router(mcp_server.router)


@app.get("/")
def health():
    return {"status": "ok"}
