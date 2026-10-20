import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LibraryDoc } from "../api/types";
import { mockFetch, renderWithProviders } from "../test-utils";
import { DeleteDialog } from "./Library";

const doc: LibraryDoc = {
  id: "doc1", title: "NVIDIA note", filename: "nvda.md", file_type: "md", size_bytes: 100, pages: null, status: "ready",
  error: null, chunk_count: 3, embedding_model: null, created_at: "2026-10-19T10:00:00Z", indexed_at: "2026-10-19T10:00:01Z",
};
const preview = {
  document_id: "doc1", title: "NVIDIA note", affected_decisions: 2, snapshot_items: 5, derived_records: 3, active_shares: 1,
  stored_exports: [], backup_retention_days: 30, backups_clear_after: "2026-11-18", erase_phrase: "ERASE",
  choices: { remove: "Deletes the file…", erase: "Also erases frozen quotations…", cannot_recall: "Downloaded exports cannot be recalled.", backups: "Backups keep it until they rotate out." },
};

afterEach(() => vi.unstubAllGlobals());

describe("DeleteDialog", () => {
  it("states the concrete effects before anything is deleted", async () => {
    mockFetch([{ path: "/library/documents/doc1/deletion-preview", body: preview }]);
    renderWithProviders(<DeleteDialog doc={doc} onClose={() => {}} />);
    expect(await screen.findByText(/Affected decisions/)).toHaveTextContent("2");
    expect(screen.getByText(/Frozen evidence items/)).toHaveTextContent("5");
    expect(screen.getByText(/Backups clear after about 2026-11-18/)).toBeInTheDocument();
  });

  it("requires the typed phrase for full erasure and sends it", async () => {
    const calls = mockFetch([
      { path: "/library/documents/doc1/deletion-preview", body: preview },
      { method: "POST", path: "/library/documents/doc1/delete", body: { ok: true, mode: "erase" } },
    ]);
    const onClose = vi.fn();
    renderWithProviders(<DeleteDialog doc={doc} onClose={onClose} />);
    fireEvent.click(await screen.findByRole("radio", { name: /Fully erase content/ }));
    const erase = screen.getByRole("button", { name: "Erase permanently" });
    expect(erase).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type ERASE to confirm/), { target: { value: "ERASE" } });
    expect(erase).toBeEnabled();
    fireEvent.click(erase);
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const del = calls.find((c) => c.method === "POST");
    expect(del?.body).toEqual({ mode: "erase", confirm_phrase: "ERASE" });
  });

  it("defaults to the reversible-in-spirit 'remove' choice without a phrase", async () => {
    const calls = mockFetch([
      { path: "/library/documents/doc1/deletion-preview", body: preview },
      { method: "POST", path: "/library/documents/doc1/delete", body: { ok: true, mode: "remove" } },
    ]);
    renderWithProviders(<DeleteDialog doc={doc} onClose={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: "Remove from Library" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ mode: "remove" });
  });
});
