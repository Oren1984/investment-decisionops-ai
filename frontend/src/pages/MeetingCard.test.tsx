import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Meeting } from "../api/types";
import { renderWithProviders } from "../test-utils";
import { MeetingCard, safeMeetingUrl } from "./Collaboration";

const view = { timezone: "Asia/Jerusalem", local: "2026-11-02T12:00:00+02:00", label: "Mon 02 Nov 12:00", utc_offset: "+0200", day_shift: 0 };
const base: Meeting = {
  id: "m1", title: "Broker call", starts_at: "2026-11-02T10:00:00Z", duration_minutes: 30, ends_at: "2026-11-02T10:30:00Z",
  timezone: "Asia/Jerusalem", provider: "manual", provider_status: "linked", provider_error: null,
  join_url: "https://meet.google.com/abc-defg-hij", link_provider: "google_meet", link_provider_label: "Google Meet",
  agenda: "", decision_id: null, owner_time: view, viewer_time: view, participants: [], simulated: false,
  provider_note: "Google Meet link pasted by the owner. Open meeting opens Google Meet in a new browser tab, outside this app.",
  recording: "Not recorded or transcribed by this app.",
};

describe("MeetingCard", () => {
  it("opens the meeting link in a new tab without leaking the opener", () => {
    renderWithProviders(<MeetingCard m={base} />);
    const link = screen.getByRole("link", { name: /Open meeting in Google Meet/ });
    expect(link).toHaveAttribute("href", "https://meet.google.com/abc-defg-hij");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
    expect(link.getAttribute("rel")).toContain("noreferrer");
    expect(screen.getByText(/Meeting service:/).parentElement).toHaveTextContent("Google Meet");
  });

  it("never renders a non-https link, even if one were stored", () => {
    renderWithProviders(<MeetingCard m={{ ...base, join_url: "javascript:alert(1)" }} />);
    expect(screen.queryByRole("link", { name: /Open meeting/ })).toBeNull();
    expect(safeMeetingUrl("http://zoom.us/j/1")).toBeNull();
    expect(safeMeetingUrl("not a url")).toBeNull();
    expect(safeMeetingUrl("https://teams.microsoft.com/l/meetup-join/x")).toBe("https://teams.microsoft.com/l/meetup-join/x");
  });

  it("shows Edit only when an edit handler is given, and labels simulated meetings", () => {
    const onEdit = vi.fn();
    const { unmount } = renderWithProviders(<MeetingCard m={base} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit meeting" }));
    expect(onEdit).toHaveBeenCalledOnce();
    unmount();
    renderWithProviders(<MeetingCard m={{ ...base, provider: "mock", provider_status: "simulated", join_url: null, link_provider: null, link_provider_label: null, simulated: true }} />);
    expect(screen.queryByRole("button", { name: "Edit meeting" })).toBeNull();
    expect(screen.getByText("Simulated – no real meeting exists")).toBeInTheDocument();
  });
});
