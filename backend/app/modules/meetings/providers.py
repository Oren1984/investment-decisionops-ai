"""Meeting providers. Docker cannot supply Zoom; the Mock provider never pretends a real meeting exists.

ZoomProvider — Server-to-Server OAuth (account_credentials grant, 1-hour tokens, no refresh token).
               STATUS: Implemented but externally unverified until the owner configures a Zoom app.
Manual link — paste a Zoom, Google Meet, Microsoft Teams or other https meeting link; "Open meeting" opens it in a
               new browser tab. No provider API is called (decision D-A: no embedded video).
Mock — "Simulated – no real meeting exists".
"""

import ipaddress
import re
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from app.config import get_settings

# Meeting-link providers: label and the hosts (and their subdomains) their links use.
LINK_PROVIDERS: dict[str, tuple[str, tuple[str, ...]]] = {
    "zoom": ("Zoom", ("zoom.us", "zoomgov.com")),
    "google_meet": ("Google Meet", ("meet.google.com",)),
    "teams": ("Microsoft Teams", ("teams.microsoft.com", "teams.live.com", "teams.cloud.microsoft")),
    "other": ("Other", ()),
}
MAX_LINK_LENGTH = 2048
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class ProviderUnavailable(Exception):
    pass


def _host_matches(host: str, hosts: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in hosts)


def detect_link_provider(host: str) -> str:
    return next((k for k, (_, hosts) in LINK_PROVIDERS.items() if hosts and _host_matches(host, hosts)), "other")


def validate_meeting_link(url: str, link_provider: str | None = None) -> tuple[str, str]:
    """Return (url, provider) for a safe external meeting link, or raise ValueError with a user-facing reason.

    Only plain https links to a public DNS name are accepted: no other schemes (javascript:, data:, http:), no
    embedded credentials, no IP addresses or localhost, no non-standard ports, no whitespace or control characters.
    A named provider must match its hosts; 'other' (or no provider) accepts any public host and is upgraded to the
    known provider when the host matches one."""
    url = (url or "").strip()
    if not url:
        raise ValueError("Paste the meeting link (https://…).")
    if len(url) > MAX_LINK_LENGTH:
        raise ValueError(f"The link is longer than {MAX_LINK_LENGTH} characters.")
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url):
        raise ValueError("The link must not contain spaces or control characters.")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise ValueError("This is not a valid link.") from exc
    if parts.scheme.lower() != "https":
        raise ValueError("Only https meeting links are allowed.")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("Links with embedded user names or passwords are not allowed.")
    if port not in (None, 443):
        raise ValueError("Links with a non-standard port are not allowed.")
    host = (parts.hostname or "").rstrip(".").lower()
    try:
        is_ip = bool(ipaddress.ip_address(host))
    except ValueError:
        is_ip = False
    if is_ip:
        raise ValueError("Use the meeting service's web address, not an IP address.")
    labels = host.split(".")
    if len(labels) < 2 or host.endswith(("localhost", ".local", ".internal")) or not all(_LABEL.match(x) for x in labels):
        raise ValueError("The link must point to a public web address.")
    if link_provider is not None and link_provider not in LINK_PROVIDERS:
        raise ValueError("Unknown meeting provider.")
    detected = detect_link_provider(host)
    if link_provider in (None, "other"):
        return url, detected
    label, hosts = LINK_PROVIDERS[link_provider]
    if not _host_matches(host, hosts):
        raise ValueError(f"This is not a {label} link ({', '.join(hosts)}). Choose the matching provider or Other.")
    return url, link_provider


def validate_zoom_link(url: str) -> str:
    return validate_meeting_link(url, "zoom")[0]


class ZoomProvider:
    def __init__(self, client: httpx.Client | None = None):
        s = get_settings()
        self.account_id, self.client_id, self.secret = s.zoom_account_id, s.zoom_client_id, s.zoom_client_secret
        self.api, self.oauth = s.zoom_api_base, s.zoom_oauth_url
        self.http = client or httpx.Client(timeout=10)
        self._token: tuple[str, float] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.account_id and self.client_id and self.secret)

    def _access_token(self) -> str:
        if self._token and self._token[1] > time.time() + 60:
            return self._token[0]
        try:
            r = self.http.post(self.oauth, params={"grant_type": "account_credentials", "account_id": self.account_id},
                               auth=(self.client_id, self.secret))
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Zoom is unreachable ({exc.__class__.__name__})") from exc
        if r.status_code != 200:
            raise ProviderUnavailable(f"Zoom OAuth failed (HTTP {r.status_code})")
        data = r.json()
        self._token = (data["access_token"], time.time() + int(data.get("expires_in", 3600)))
        return self._token[0]

    def _body(self, title: str, starts_at: datetime, duration: int, timezone: str, agenda: str) -> dict:
        return {"topic": title[:200], "type": 2, "start_time": starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration": duration, "timezone": timezone, "agenda": agenda[:2000],
                "settings": {"auto_recording": "none", "waiting_room": True}}

    def create(self, title: str, starts_at: datetime, duration: int, timezone: str, agenda: str) -> dict:
        token = self._access_token()
        try:
            r = self.http.post(f"{self.api}/users/me/meetings", headers={"Authorization": f"Bearer {token}"},
                               json=self._body(title, starts_at, duration, timezone, agenda))
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Zoom is unreachable ({exc.__class__.__name__})") from exc
        if r.status_code not in (200, 201):
            raise ProviderUnavailable(f"Zoom rejected the meeting (HTTP {r.status_code})")
        data = r.json()
        return {"provider_meeting_id": str(data["id"]), "join_url": data["join_url"]}

    def update(self, meeting_id: str, title: str, starts_at: datetime, duration: int, timezone: str,
               agenda: str) -> None:
        token = self._access_token()
        try:
            r = self.http.patch(f"{self.api}/meetings/{meeting_id}", headers={"Authorization": f"Bearer {token}"},
                                json=self._body(title, starts_at, duration, timezone, agenda))
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Zoom is unreachable ({exc.__class__.__name__})") from exc
        if r.status_code not in (200, 204):
            raise ProviderUnavailable(f"Zoom rejected the update (HTTP {r.status_code})")
