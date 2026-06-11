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

1. Attach the app container to the `proxy` network:

   ```yaml
   services:
     myapp:
       image: myapp:latest
       networks:
         - proxy

   networks:
     proxy:
       external: true
       name: proxy
   ```

2. Add a site block to your `Caddyfile` (your local copy of `Caddyfile.example`
   — run `cp Caddyfile.example Caddyfile` first if you haven't already):

   ```caddy
   myapp.{$CF_DOMAIN} {
       import cf_tls
       reverse_proxy myapp:8080
   }
   ```

   `myapp` is the container name and `8080` its internal port; the app publishes
   no host ports of its own. Keep new blocks here in your local `Caddyfile` —
   `Caddyfile.example` stays as the pristine template.

3. Reload Caddy:

   ```bash
   docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```

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
