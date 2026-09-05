# Server deployment

One Astro Canvas for a research group: HTTPS, login accounts, a private workspace per person and
a shared read-only folder. The reference stack is Docker Compose — the app, Postgres for the
accounts, and Caddy for TLS.

## Five minutes

```sh
git clone https://github.com/lblogan14/astro-canvas
cd astro-canvas
cp deploy/.env.example deploy/.env
$EDITOR deploy/.env        # POSTGRES_PASSWORD, CANVAS_DOMAIN, ADMIN_EMAILS
docker compose -f deploy/compose.yaml up -d --build
```

With the defaults (`CANVAS_DOMAIN=localhost`, `CANVAS_TLS=internal`) that is real HTTPS on
`https://localhost` straight away, using Caddy's own local CA — no ACME round trip, useful for a
trial. Point `CANVAS_DOMAIN` at a real name and put an email address in `CANVAS_TLS` and the same
directive fetches a Let's Encrypt certificate instead.

Then open the site, register with an address you listed in `ADMIN_EMAILS`, and you are the
administrator.

## What is in the stack

| Service | Job |
|---|---|
| `app` | The app itself, `--auth users`, plain HTTP on the internal network |
| `db` | Postgres 17: the accounts, and nothing else |
| `caddy` | TLS, the WebSocket upgrade, security headers, an 8 GiB body limit for cube uploads |

The image is built in three stages so the runtime carries neither Node nor a build toolchain:
pnpm builds the SPA, `uv` builds all four wheels, and a slim `python:3.12` installs them into
`/opt/venv`. `uv` itself stays in the runtime image on purpose — it is what the pack manager
shells out to, and it sits next to the interpreter, which is exactly where the manager looks
first.

## Isolation

Each user gets their own **engine**, created on first request:

- their own workspace at `/data/users/<user id>` — workflows, uploads, results, cache;
- their own run queue, thread pool and process pool;
- their own event stream, so one person's run never appears in another's session;
- their own **trust decisions**, because trusting a code snippet means running it.

Nothing is shared except the accounts table and `/data/shared`, which is mounted read-only into
every workspace as `shared/`. Put your group's line lists and reference spectra there:

```sh
docker compose -f deploy/compose.yaml cp atlas.fits app:/data/shared/
```

Users see `shared/` in the file browser, can read and load from it, and get a 403 if anything
tries to write to it.

`/api/workspace/select` is refused in this mode: nobody can repoint the server at a folder of
their choosing.

## Administrators

`ADMIN_EMAILS` is a comma-separated list, matched case-insensitively when an account registers.
An administrator gets one extra thing: **the pack manager**.

That is not a cosmetic distinction. The manager installs into the *server's* Python environment,
so installing a pack changes what every user runs. `/api/manager/*` therefore returns 403 for
everyone else, the menu entry is hidden, and typing `/manager` bounces back to the canvas. The
trust routes are deliberately *not* behind that flag: those are about the code in your own
documents.

A shared server should also stay on the curated registry — `PACK_SECURITY=strict` is the default
in `.env.example`, which means registry packs only, no arbitrary PyPI names, no git URLs, no
local paths. Set `MANAGER=false` to serve without `/api/manager` at all, for nobody.

## Accounts

Registration is open by default so your group can sign themselves up. Once everybody has:

```sh
REGISTRATION=false docker compose -f deploy/compose.yaml up -d app
```

New accounts then have to come from an OAuth provider, or from a row in the database.

### GitHub and ORCID

Set the client credentials and the provider appears on the login page:

```sh
ASTRO_CANVAS_OAUTH_GITHUB_CLIENT_ID=...
ASTRO_CANVAS_OAUTH_GITHUB_CLIENT_SECRET=...

# ORCID, or any OpenID Connect provider
ASTRO_CANVAS_OIDC_NAME=orcid
ASTRO_CANVAS_OIDC_CLIENT_ID=...
ASTRO_CANVAS_OIDC_CLIENT_SECRET=...
ASTRO_CANVAS_OIDC_CONFIGURATION_URL=https://orcid.org/.well-known/openid-configuration
```

The callback to register with the provider is
`https://<your domain>/api/auth/<name>/callback`. Accounts are matched by verified email, so
somebody who signed up with a password can link a provider later without becoming two people.

### Sessions

Browsers get an httpOnly cookie (`SameSite=Lax`, and `Secure` whenever `PUBLIC_URL` is
`https://`); scripts and the CLI can use the same JWT as a bearer token:

```sh
TOKEN=$(curl -s -X POST https://canvas.lab.example/api/auth/bearer/login \
  -d "username=you@lab.example" -d "password=..." | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" https://canvas.lab.example/api/workflows
```

Sessions last a week. The signing secret is generated once and kept in the config folder inside
the volume, so a restart does not log everybody out; set `ASTRO_CANVAS_SECRET` yourself if you
run more than one replica.

## Settings

Everything in `deploy/.env.example`, with the ones worth thinking about:

| | Default | |
|---|---|---|
| `POSTGRES_PASSWORD` | *(required)* | Compose refuses to start without it |
| `CANVAS_DOMAIN` | `localhost` | What Caddy serves |
| `CANVAS_TLS` | `internal` | `internal` for Caddy's local CA, an email for Let's Encrypt |
| `ADMIN_EMAILS` | — | Addresses promoted to administrator on registration |
| `REGISTRATION` | `true` | Self-service sign-up |
| `PACK_SECURITY` | `strict` | Registry packs only |
| `MANAGER` | `true` | `false` serves without `/api/manager` entirely |
| `CACHE_MEMORY_MB` | `1024` | Per user. Multiply by concurrent users, not by accounts |
| `CACHE_DISK_GB` | `50` | Per user, under `/data` |
| `MAX_WORKERS` | `4` | Per user |
| `RUN_TIMEOUT_S` | `3600` | Wall clock per run |

**Size the machine for concurrent users, not for accounts.** An engine is created on a user's
first request and holds caches and pools until the process restarts; ten accounts who use it on
different days cost about what one active user costs.

## Backups

Two things matter and they are both volumes:

```sh
# the accounts
docker compose -f deploy/compose.yaml exec -T db pg_dump -U canvas canvas > accounts.sql

# everybody's workspaces
docker run --rm -v astro-canvas_data:/data -v "$PWD:/backup" alpine \
  tar czf /backup/workspaces.tar.gz -C /data .
```

`/data/*/.astro-canvas/blobs` is the cache: large, and reproducible from the workflows. Excluding
it makes the backup much smaller at the cost of a recompute after a restore.

## Upgrading

```sh
docker compose -f deploy/compose.yaml pull
docker compose -f deploy/compose.yaml up -d
```

Migrations for both databases run at startup. Take a `pg_dump` first anyway.

## Without Docker

Nothing about `--auth users` needs a container:

```sh
uv tool install 'astro-canvas[users]' --python 3.12 --with astro-canvas-rbcodes

ASTRO_CANVAS_DATABASE_URL=postgresql://canvas:...@localhost/canvas \
ASTRO_CANVAS_PUBLIC_URL=https://canvas.lab.example \
ASTRO_CANVAS_ADMIN_EMAILS=pi@lab.example \
ASTRO_CANVAS_USERS_DIR=/srv/astro-canvas/users \
ASTRO_CANVAS_SHARED_DIR=/srv/astro-canvas/shared \
astro-canvas serve --host 0.0.0.0 --auth users
```

The `users` extra carries fastapi-users, asyncpg and aiosqlite; without a `DATABASE_URL` the
accounts go in a SQLite file in the config folder, which is fine for a handful of people on one
box. Put a TLS terminator in front either way, and set `PUBLIC_URL` so the session cookie gets
its `Secure` flag.

## Verifying a deployment

```sh
deploy/tests/compose.sh
```

Builds the image, brings the stack up and checks the whole story through the TLS endpoint: HTTPS
answers, anonymous requests get 401, two accounts log in with Secure cookies, each gets a
different workspace, one cannot read the other's workflow, a member gets 403 from the manager
while an admin does not, the accounts really are in Postgres, `astro-canvas doctor` is green
inside the image, and the exposure guard still refuses `--auth token` on `0.0.0.0`.
