# exam-server

One FastAPI app, one deployment, six graded endpoints as different routes on
the same HTTPS domain — this is how all the tasks can be "live at once"
without juggling five separate hosts:

| Task | Route |
|---|---|
| Spec-Driven Development (Proration) | `POST /proration` |
| Guardrail Red-Team Round-Trip | `POST /redteam-guardrail` |
| Agent Harness — Pre-Tool-Call Guardrail | `POST /agent-guardrail` |
| Skill Safety Audit Scanner | `POST /skill-scanner` |
| Agent Harness — Run Budget & Loop Guard | `POST /budget-loop-guard` |
| Live MCP Server | `POST /mcp` (Streamable HTTP) |

All logic has been tested locally against the worked examples / attack cases
each task describes (see the transcript from building this — every case
passed). The A2A Invoice Agent is **not** included here: it needs a real LLM
API key and durable per-task storage, and is a much bigger build — ask
separately and I'll scaffold it the same way once you've picked an LLM
provider.

## 1. Before you deploy: edit your registered email

Open `app/mcp_server.py` and set `REGISTERED_EMAIL` to your actual
registered exam email if it isn't already correct.

## 2. Deploy (Fly.io example — free tier, keeps a machine always running)

```bash
# from inside the exam-server/ directory
curl -L https://fly.io/install.sh | sh   # install flyctl if you don't have it
fly auth login
fly launch --no-deploy      # creates/edits fly.toml, pick a unique app name
fly deploy
```

Your endpoints will be live at `https://<your-app-name>.fly.dev/<route>`.

`fly.toml` is already set with `min_machines_running = 1` and
`auto_stop_machines = false` so the grader never hits a cold start.

### Alternative: any VPS with Docker

```bash
docker build -t exam-server .
docker run -d -p 443:8080 --restart unless-stopped exam-server
# put this behind Caddy or nginx for automatic HTTPS if you don't already
# have a cert, e.g. a one-line Caddyfile:
#   your-domain.com {
#     reverse_proxy localhost:8080
#   }
```

### Alternative: Render / Railway

Push this repo, point either platform at the `Dockerfile`, expose port
`8080`. On Render's free tier the service can sleep after inactivity —
if you use it, either upgrade to a paid "always on" instance or ping the
health endpoint (`GET /`) every few minutes with a cron job so it stays
warm through grading.

## 3. Seed files (redteam guardrail task only)

`create_seed_files.sh` runs automatically inside the Docker build
(`Dockerfile` calls it), so the four required files already exist at
`/srv/agent-redteam/...` inside the container. If you deploy without
Docker (e.g. directly on a VPS), run this script manually first:

```bash
sudo ./create_seed_files.sh
```

## 4. Submit these URLs to each grader

```
https://<your-app>.fly.dev/proration
https://<your-app>.fly.dev/redteam-guardrail
https://<your-app>.fly.dev/agent-guardrail
https://<your-app>.fly.dev/skill-scanner
https://<your-app>.fly.dev/budget-loop-guard
https://<your-app>.fly.dev/mcp
```

## 5. Smoke-test after deploying

```bash
curl https://<your-app>.fly.dev/
curl -X POST https://<your-app>.fly.dev/proration \
  -H 'Content-Type: application/json' \
  -d '{"old_price":19,"new_price":69,"days_remaining":19,"days_in_actual_month":31,"spec":"v2"}'
# -> {"charge": 30.645...}
```

If a route returns nothing / times out, check `fly logs` (or your
platform's logs) — most likely cause is a missing dependency or the
container not binding to `0.0.0.0:8080`.

## Notes on the harder judgment calls

- **redteam-guardrail / fetch_url**: does a live DNS resolution + IP-range
  check on every host, and re-validates every redirect hop before following
  it (so a redirect to a private IP is caught, not just the initial URL).
- **agent-guardrail / bash**: since we never execute the agent's shell
  command, credential-file detection is heuristic — it expands `$HOME`/`~`,
  resolves `..` traversal against the known working directory, and
  recursively base64-decodes suspicious tokens before searching for the
  forbidden path. This is deliberately conservative about the *one*
  forbidden file and permissive about everything else, per the stated
  policy ("reads elsewhere are fine").
- **skill-scanner**: tuned toward precision (few false positives) since the
  grading metric is F-beta(0.5), which punishes over-claiming harder than
  under-claiming.
- **mcp_server**: responds with plain JSON (not SSE) since the tool doesn't
  need server-initiated pushes; this is valid per the Streamable HTTP
  transport spec, which allows either.
