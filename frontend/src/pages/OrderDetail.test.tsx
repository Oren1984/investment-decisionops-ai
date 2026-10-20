import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { OrderPreview } from "../api/types";
import { renderWithProviders } from "../test-utils";
import { OrderPreviewView } from "./OrderDetail";

const preview: OrderPreview = {
  mode: "mock", broker: "mock", account_id: "MOCK-0001",
  instrument: { symbol: "AAPL", name: "Apple Inc.", broker_instrument_id: null, venue_mic: "XNAS" },
  currency: "USD", side: "buy", quantity: 2, order_type: "limit", limit_price: 190.5, stop_price: null, tif: "DAY",
  estimated_commission: { amount: null, currency: null, label: "Unknown", detail: null, unknown: true },
  notional: { amount: 381, currency: "USD", home_amount: 1409.7, home_currency: "ILS", fx_rate: 3.7, fx_as_of: "2026-10-19T12:00:00Z", reference_price: 190.5 },
  quote: { instrument_id: "i1", symbol: "AAPL", price: 190.5, change_pct: 0.2, currency: "USD", as_of: "2026-10-19T12:00:00Z", age_seconds: 400, freshness: "stale", label: "Synthetic" } as OrderPreview["quote"],
  session: { state: "closed", reason: null, next_event: null },
  limit_checks: [
    { key: "notional", name: "Order value within your per-order limit", passed: true, detail: "1,410 vs limit 150,000 ILS" },
    { key: "quote_fresh", name: "Quote is fresh", passed: false, detail: "Quote age 400 s (stale)" },
  ],
  all_checks_passed: false, linked_decision: null, client_order_id: "DOPS-abc", payload_hash: "f".repeat(64), label: "Simulated", mock_scenario: null,
};

describe("OrderPreviewView", () => {
  it("shows unknown costs explicitly instead of a number", () => {
    renderWithProviders(<OrderPreviewView p={preview} />);
    expect(screen.getByText("Estimated commission").nextSibling).toHaveTextContent("Unknown");
  });

  it("counts checks and announces failures to screen readers", () => {
    renderWithProviders(<OrderPreviewView p={preview} />);
    expect(screen.getByText(/Limit and safety checks \(1\/2 passed\)/)).toBeInTheDocument();
    expect(screen.getByText("Failed:")).toBeInTheDocument();
    expect(screen.getByText(/Quote age 400 s \(stale\)/)).toBeInTheDocument();
  });

  it("shows the broker estimate when one exists", () => {
    renderWithProviders(
      <OrderPreviewView p={{ ...preview, estimated_commission: { amount: 1.25, currency: "USD", label: "Simulated estimate", detail: null, unknown: false } }} />,
    );
    expect(screen.getByText("1.25 USD (Simulated estimate)")).toBeInTheDocument();
  });
});
