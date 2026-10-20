---
title: Security, privacy and your data
category: Settings
summary: Sign-in, sessions, two-step sign-in, export and deletion.
routes: /settings
---
- Passwords are hashed with Argon2id (minimum 12 characters). Sessions are server-side, end after 30 minutes idle or 12 hours, and logout invalidates them immediately.
- Optional authenticator-app sign-in (TOTP) with 10 one-time recovery codes.
- Approvals and sensitive settings ask for your password again (valid 5 minutes).
- Secrets live only in `.env` (never in the repository, images, logs or screenshots).
- **Export** creates a ZIP of all your data and documents (secrets excluded).
- **Delete all personal data** erases everything and returns the workspace to first-run setup.
- Retention defaults: audit 7 years, run details 2 years, sessions 30 days, backups 30 days.
