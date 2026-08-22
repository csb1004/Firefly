import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Reveal } from "./Reveal";

describe("Reveal", () => {
  it("shows every card in a ten-draw result", () => {
    const onClose = vi.fn();
    const cards = Array.from({ length: 10 }, (_, index) => ({
      id: String(index),
      name: `카드 ${index + 1}`,
      rarity: index === 7 ? 5 : 3,
      yp: 100,
      image_url: `/card-${index}.webp`,
    }));

    render(<Reveal cards={cards} onClose={onClose}/>);

    expect(screen.getByRole("dialog", { name: "10장 카드 획득" })).toHaveClass("reveal-5", "batch");
    for (const card of cards) expect(screen.getByText(card.name)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "확인" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
