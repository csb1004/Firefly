import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { DrawHistoryPage } from "./DrawHistory";

vi.mock("../api", () => ({ api: vi.fn() }));

const response = {
  page: 1,
  page_size: 50,
  total: 51,
  summary: { total_draws: 51, four_remaining: 7, five_remaining: 39 },
  items: [{
    id: "draw-1",
    draw_number: 51,
    drawn_at: "2026-08-24T00:00:00+00:00",
    draw_day: "2026-08-24",
    ticket_source: "bonus" as const,
    batch_id: "batch-1",
    batch_position: 3,
    card_id: "card-1",
    card_name: "황금 카드",
    card_rarity: 5,
    card_yp: 500,
    image_url: "/card.webp",
  }, {
    id: "draw-2",
    draw_number: 50,
    drawn_at: "2026-08-23T00:00:00+00:00",
    draw_day: "2026-08-23",
    ticket_source: "daily" as const,
    batch_id: null,
    batch_position: null,
    card_id: "card-2",
    card_name: "출석 카드",
    card_rarity: 3,
    card_yp: 300,
    image_url: "/daily-card.webp",
  }],
};

describe("DrawHistoryPage", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockResolvedValue(response);
  });

  it("shows lifetime draw numbers, pity summary, and ticket sources only", async () => {
    render(<DrawHistoryPage onCard={vi.fn()}/>);

    expect(await screen.findByText("#51")).toBeInTheDocument();
    expect(screen.getByText("황금 카드")).toBeInTheDocument();
    expect(screen.getByText("추가 뽑기권")).toBeInTheDocument();
    expect(screen.getByText("출석 뽑기권")).toBeInTheDocument();
    expect(screen.queryByText(/10회 뽑기|1회 뽑기|번째/)).not.toBeInTheDocument();
    expect(screen.getByText("39회")).toBeInTheDocument();
  });

  it("opens card details and requests the next history page", async () => {
    const onCard = vi.fn();
    render(<DrawHistoryPage onCard={onCard}/>);
    fireEvent.click(await screen.findByRole("button", { name: "황금 카드 상세 보기" }));
    expect(onCard).toHaveBeenCalledWith("card-1");

    fireEvent.click(screen.getByRole("button", { name: "다음" }));
    await waitFor(() => expect(api).toHaveBeenLastCalledWith("/api/draw/history?page=2&page_size=50"));
  });
});
