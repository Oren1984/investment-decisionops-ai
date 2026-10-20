---
title: First run and account recovery
category: Setup
summary: Setup token, forgotten password and lost authenticator.
routes: /
---
## First run

After `docker compose up --build`, the API prints a **one-time setup token** in its logs:

```
docker compose logs api
```

Paste it on the setup page (valid 24 hours, single use). To print a new one: `docker compose exec api python -m app.cli setup-token`.

## Forgot your password

Local machine access is the trust anchor. Run:

```
docker compose exec api python -m app.cli reset-owner-password
```

It prints a temporary password and signs out every session. Change it immediately in Settings → Security.

## Lost authenticator

Sign in with one of your **recovery codes**. If you have none left, reset the password with the command above, then turn two-step sign-in off and on again.

## Too many attempts

After 5 failed sign-ins for an account (or 20 from one client) within 15 minutes, sign-in pauses for 15 minutes.
