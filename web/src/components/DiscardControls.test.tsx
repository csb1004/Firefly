import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Card } from "../types";
import { DiscardControls } from "./DiscardControls";

const card: Card = {
  id: "card-1",
  name: "별빛 카드",
  rarity: 5,
  yp: 500,
  image_url: "/card.webp",
  quantity: 2,
  available_quantity: 2,
};

describe("DiscardControls", () => {
  it("keeps discard actions hidden until the card menu is opened", () => {
    render(<DiscardControls card={card} onDiscarded={vi.fn()} onError={vi.fn()}/>);

    const toggle = screen.getByRole("button", { name: "별빛 카드 카드 정리" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "변화 확인" })).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "변화 확인" })).toBeInTheDocument();
    expect(screen.getByLabelText("별빛 카드 버릴 수량")).toHaveValue(1);
  });
});
