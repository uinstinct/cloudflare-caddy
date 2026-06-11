# Cloudflare Caddy Reverse Proxy

[![CI](https://github.com/uinstinct/cloudflare-caddy/actions/workflows/ci.yml/badge.svg)](https://github.com/uinstinct/cloudflare-caddy/actions/workflows/ci.yml)

A single-command Docker stack that provisions a Caddy reverse proxy with a Cloudflare Origin CA wildcard certificate, idempotent DNS and SSL management, and a reusable `proxy` network for your app containers.

## Quick Start

```bash
# 1. Clone and enter the repo
git clone https://github.com/uinstinct/cloudflare-caddy.git
cd cloudflare-caddy

# 2. Configure environment
cp .env.example .env
# Edit .env and set CF_DOMAIN and CF_API_TOKEN

# 3. Create your Caddyfile from the template
cp Caddyfile.example Caddyfile
# Edit Caddyfile to add your app site blocks (see "Adding a New App")

# 4. Start everything
docker compose up -d
```

> Both `.env` and `Caddyfile` are gitignored working copies — edit them freely
> without dirtying the repo or hitting merge conflicts on `git pull`. The tracked
> templates are `.env.example` and `Caddyfile.example`.

The bootstrap service runs once, provisions DNS and certificates, then Caddy starts and serves traffic on `443`.

## Required Cloudflare API Token Permissions

Create a single API token at https://dash.cloudflare.com/profile/api-tokens with these permissions:

| Permission | Level |
|---|---|
| Zone:Read | All zones |
| DNS:Edit | All zones |
| Zone Settings:Edit | All zones |
| SSL and Certificates:Edit | All zones |

> `Zone Settings:Edit` is required for the SSL/TLS encryption mode step
> (`/settings/ssl`); it is a **separate** permission group from
> `SSL and Certificates:Edit` (which only covers the Origin CA certificate API).
> Omitting it causes `9109: Unauthorized to access requested resource`.

Use **Zone Resources: Include - All zones** (or restrict to the specific zone).

## Architecture

```
┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│  cloudflare-setup   │─────▶│       Caddy         │◀─────│   Your App Stack    │
│  (runs once)        │      │   (reverse proxy)   │      │   (joins proxy net) │
└─────────────────────┘      └─────────────────────┘      └─────────────────────┘
         │                              │
    Cloudflare API               Origin CA cert
    DNS + SSL mode               (wildcard, ~15yr)
```
<details>
<summary>What <code>cloudflare-setup</code> does</summary>

Verifies the API token, ensures a wildcard DNS record (`*.domain`), optionally manages the apex record, sets SSL mode to Strict, generates a private key + CSR, and creates or reuses a Cloudflare Origin CA certificate (written to disk as `origin.pem` + `origin.key`).
</details>


- **`cloudflare-setup`** — Idempotent Python bootstrap. Verifies the API token, ensures a wildcard DNS record (`*.domain`), optionally manages the apex record, sets SSL mode to Strict, and creates or reuses a Cloudflare Origin CA certificate covering `domain` and `*.domain`.
- **`caddy`** — Loads the generated certificate explicitly, serves HTTPS on `443` only (ACME and port-80 redirects disabled), and proxies traffic to containers attached to the `proxy` network.
- **`proxy` network** — A fixed-name Docker bridge network (`proxy`) so any external compose stack can join without `docker network create`.

## Commands

| Command | Purpose |
|---|---|
| `docker compose up -d` | Start Caddy and the bootstrap service |
| `docker compose --profile demo up -d` | Start the stack plus a demo `whoami` container |
| `docker compose logs -f cloudflare-setup` | Watch bootstrap progress live |
| `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile` | Reload Caddy after editing the Caddyfile |
| `docker compose down -v` | Tear everything down and remove volumes |

## Adding a New App

Every app needs two edits — one in the **app's own** `docker-compose.yml`, one in
**this repo's** `Caddyfile` — then a reload. The example below exposes a container
named `myapp` listening on port `8080` at `https://myapp.<your-domain>`. Adjust
the three highlighted values (`myapp`, `myapp`, `8080`) to match your app.

You don't touch Cloudflare or DNS: the wildcard record (`*.domain`) and wildcard
certificate created at setup already cover every subdomain.

### 1. Join the app to the `proxy` network

In your app's **own** `docker-compose.yml` (a separate project from this repo),
attach the service to the shared `proxy` network. Do **not** publish host ports —
Caddy reaches the container directly over the network.

```yaml
services:
  myapp:                 # ← container name, used as the upstream below
    image: myapp:latest
    networks:
      - proxy
    # no `ports:` — traffic arrives through Caddy, not the host

networks:
  proxy:
    external: true       # the network is created by this stack, not the app
    name: proxy
```

Start it as usual (`docker compose up -d`) so the container is running and on the
network.

### 2. Add a site block to the `Caddyfile`

Edit **this repo's** `Caddyfile` (your local copy of `Caddyfile.example` — run
`cp Caddyfile.example Caddyfile` first if you haven't already) and add:

```caddy
myapp.{$CF_DOMAIN} {       # ← the public subdomain
    import cf_tls          # loads the Origin CA cert (don't change)
    reverse_proxy myapp:8080   # ← <container-name>:<container-port>
}
```

- The subdomain (`myapp`) is whatever you want the app reachable at.
- `myapp:8080` is the **container name** and its **internal** port from step 1.
- `import cf_tls` is required so the site serves the Cloudflare Origin CA
  certificate; copy it verbatim into every block.

Keep your blocks in `Caddyfile` only — `Caddyfile.example` stays as the pristine
template so `git pull` never conflicts.

### 3. Reload Caddy

Apply the new config with zero downtime (no restart needed):

```bash
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Your app is now live at `https://myapp.<your-domain>`. Repeat steps 1–3 for each
additional app.

## Offline Mode

Set `CF_OFFLINE=true` in `.env` to skip all Cloudflare API calls and generate a self-signed certificate locally. Useful for:

- Running the stack without a Cloudflare account
- CI integration tests (see `.github/workflows/ci.yml`)
- Local development and debugging

In offline mode the bootstrap still writes a valid key + certificate to `./certs/`, and Caddy starts successfully.

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `CF_DOMAIN` | *(required)* | Your Cloudflare zone apex — just the naked domain, no `https://`, no `*.` wildcard prefix, no trailing slash (e.g. `example.com`) |
| `CF_API_TOKEN` | *(required)* | Cloudflare API token with Zone:Read, DNS:Edit, Zone Settings:Edit, SSL and Certificates:Edit |
| `SERVER_IP` | *(auto-detected)* | Public IP for DNS A records. Detected via `api.ipify.org` if omitted |
| `MANAGE_APEX` | `false` | Also create/update the apex (`@`) A record |
| `CERT_VALIDITY_DAYS` | `5475` | Origin CA certificate lifetime in days (`7/30/90/365/730/1095/5475`) |
| `CF_OFFLINE` | `false` | Skip Cloudflare and generate a self-signed certificate |
| `CERT_DIR` | `/certs` | Mount point for certificates inside the bootstrap container |

See `.env.example` for the full list with inline documentation.

## CI / Testing

GitHub Actions runs on every push and PR:

- **Unit tests** — `pytest` with mocked Cloudflare API (`respx`)
- **Lint & format** — `ruff`
- **Integration test** — Builds the Docker stack in offline mode, verifies Caddy starts, curls the proxy, checks certificate SANs, and re-runs the bootstrap to prove idempotency

## File Layout

```
.
├── Caddyfile.example         # Caddy config template (tracked)
├── Caddyfile                 # Your working copy — copied from the example (gitignored)
├── docker-compose.yml        # Orchestrates bootstrap + Caddy + demo profile
├── .env.example              # Documented environment template
├── .github/workflows/ci.yml  # GitHub Actions (unit + integration tests)
├── setup/                    # Python/UV bootstrap project
│   ├── cf_setup/             # Source package
│   ├── tests/                # pytest suite (39 tests)
│   ├── Dockerfile            # Two-stage UV build
│   └── pyproject.toml        # Dependencies and tool config
├── certs/                    # Generated certificates (gitignored)
├── data/                     # Caddy runtime data (gitignored)
└── config/                   # Caddy config storage (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
