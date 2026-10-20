# Deployment

**Nothing is deployed.** No cloud account, provisioning, spending or DNS change has been authorized. The app runs
locally with Docker Compose; the same stack runs unchanged on any single Linux VM with Docker.

## Recommended target (plan §19, owner decision D-B pending)

AWS Lightsail, Frankfurt (`eu-central-1`), 4 GB bundle (2 vCPU / 4 GB / 80 GB SSD, US$24/month as published on
18 Oct 2026, IPv4 included), daily automatic snapshots. Hetzner Cloud remains the documented alternative. No
server-side LLM (CPU servers are too slow for the chat model); model mode stays a local-machine feature.

## Terraform module: `infra/terraform/lightsail/`

| File | Contents |
| --- | --- |
| `versions.tf` | Terraform ≥ 1.9, `hashicorp/aws ~> 6.69`; local state (git-ignored) |
| `variables.tf` | Region/AZ, name, bundle, blueprint, SSH public key, SSH CIDRs (validated; `0.0.0.0/0` rejected), deploy user, snapshot time, optional disk size, tags |
| `main.tf` | Key pair (public key only), instance with `AutoSnapshot` add-on, static IP + attachment, firewall (80/443 public, 22 from owner CIDRs only), optional block disk + attachment |
| `launch.sh.tftpl` | Launch script run by cloud-init: non-root deploy user (key-only), SSH password and root login disabled, unattended upgrades, Docker Engine + Compose plugin from Docker's apt repository, optional data disk mounted as Docker's data root |
| `outputs.tf` | Static IP, instance name, SSH command, disk name |
| `terraform.tfvars.example` | Example values; copy to `terraform.tfvars` (git-ignored) |

No secrets are in Terraform variables or state. Bundle and blueprint IDs must be re-checked with
`aws lightsail get-bundles` / `get-blueprints` before any apply.

### Checks performed (20 Oct 2026)

| Check | Result |
| --- | --- |
| `terraform fmt -check` | Passed |
| `terraform init -backend=false` | Passed (`hashicorp/aws` v6.69.1) |
| `terraform validate` | Passed |
| `tflint` (v0.59.1, container, default ruleset) | Passed, no findings |
| `plan`, `apply`, TLS issuance, snapshot restore, remote E2E | **Not performed: not authorized** |

The checks ran in the official `hashicorp/terraform:1.15.8` container. On this Windows host the native Terraform
binary could not load the AWS provider (`x509: certificate signed by unknown authority` on the local
Terraform↔plugin handshake, most likely local TLS interception), so the containerized run is the recorded evidence.

## What a deployment would still need (owner actions and remaining work)

1. AWS account with MFA and a Lightsail-only IAM user; owner's domain and SSH key; decision D-B.
2. `terraform apply` (owner-authorized), then point the domain's A record at the static IP.
3. **A server Compose override and Caddyfile with the domain and automatic HTTPS** (Let's Encrypt). This override is
   **not written yet**: the committed `deploy/Caddyfile` is the local, HTTP-only, loopback configuration.
   `COOKIE_SECURE=true` must be set behind TLS.
4. Copy the app and a fresh `.env` (new secrets, never the local one) to `/opt/decisionops` over SSH as the deploy
   user; `docker compose up -d --build`.
5. Nightly `scripts/backup.sh` via cron, copied off-instance; Lightsail snapshots cover the disk.
6. Before any public exposure: enforced owner TOTP and a security review. IB Gateway on a server needs its own
   interactive 2FA, so Paper/Live from a server is a separate decision. The demo is local-only (D6).
