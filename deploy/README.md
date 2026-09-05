# Lab server

Astro Canvas for a research group: the app behind Caddy (TLS), Postgres for the accounts, and
one workspace per user under a `/data` volume. Full guide:
[docs/deploy/server.md](../docs/deploy/server.md).

```sh
cp deploy/.env.example deploy/.env      # set POSTGRES_PASSWORD, CANVAS_DOMAIN, ADMIN_EMAILS
docker compose -f deploy/compose.yaml up -d --build
```

| File | What it is |
|---|---|
| `Dockerfile` | Three stages: pnpm builds the SPA, uv builds the wheels, a slim runtime installs them |
| `compose.yaml` | `app` + `db` (Postgres) + `caddy`, with the `data` volume |
| `Caddyfile` | TLS, the WebSocket upgrade, security headers |
| `.env.example` | Every setting the stack reads, with defaults |
| `tests/compose.sh` | Acceptance: HTTPS answers, two users log in isolated, admin-only Manager |

Everything Python here goes through `uv`; there is no `pip` in this folder (CONTRIBUTING).
`uv` stays in the runtime image on purpose — it is what the pack manager runs, and it sits next
to the interpreter so `find_uv` needs no configuration.
