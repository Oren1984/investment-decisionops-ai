---
title: Meetings — Zoom, Google Meet, Microsoft Teams and other links
category: Collaboration
summary: Add or edit a meeting link from any provider, open it in a new tab, and keep the companion page beside it.
routes: /collaboration
---
## Add a meeting link

1. **Collaboration → Meetings → Schedule meeting** (or **Edit meeting** on an existing card).
2. **Meeting type:**
   - **Meeting link (Zoom, Google Meet, Teams, other)**: paste a link you created in the meeting service.
   - **Simulated**: a preview card only — *“Simulated – no real meeting exists.”* (Mock mode and the demo).
   - **Schedule through Zoom API**: creates the Zoom meeting for you, only if a Zoom app is configured (see below).
3. **Meeting provider:** Zoom, Google Meet, Microsoft Teams, or **Other** for any other service (for example Webex or Jitsi).
4. **Meeting link:** paste the full `https://…` link and **Save meeting**. Edit it at any time the same way.

## Which links are accepted

Only plain **https** links to a public web address. The link must match the chosen provider:

| Provider | Link must be on |
| --- | --- |
| Zoom | `zoom.us` or `zoomgov.com` (including company subdomains such as `us02web.zoom.us`) |
| Google Meet | `meet.google.com` |
| Microsoft Teams | `teams.microsoft.com`, `teams.live.com` or `teams.cloud.microsoft` |
| Other | any public https address |

Refused, with the reason shown: `http://` and other schemes (`javascript:`, `data:` …), links with a user name or password
inside, IP addresses, `localhost` or internal names, non-standard ports, spaces, and links longer than 2,048 characters.
If you paste a Google Meet link with “Other” selected, it is recognised as Google Meet.

## Join

**Open meeting ↗** opens the link in a **new browser tab** (or the provider's app, if your computer hands it over). The
meeting page cannot reach back into this app (`noopener`). Nothing is embedded, and meetings are **never recorded or
transcribed** by this app. Keep the **companion page** open beside the call for the agenda, the shared decision, notes,
action items and comments. Collaborators you invited see the link only for meetings shared with them.

## Zoom API scheduling (optional)

With a Zoom Server-to-Server OAuth app (`ZOOM_ACCOUNT_ID`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` in `.env`), “Schedule
through Zoom API” creates and updates the Zoom meeting for you. If Zoom is unreachable the meeting is kept as a draft with
the reason. Status: **implemented but externally unverified** until you configure it. Google Meet and Teams have no
scheduling integration: paste their links. Zoom Basic accounts may limit group meetings to about 40 minutes.
