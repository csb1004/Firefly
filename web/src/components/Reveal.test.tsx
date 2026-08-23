import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Reveal } from "./Reveal";

describe("Reveal", () => {
  it("shows every card in a ten-draw result", () => {
    const onClose = vi.fn();
    const rarities = [1, 5, 3, 4, 2, 5, 1, 3, 4, 2];
    const cards = Array.from({ length: 10 }, (_, index) => ({
      id: String(index),
      name: `카드 ${index + 1}`,
      rarity: rarities[index],
      yp: 100,
      image_url: `/card-${index}.webp`,
    }));

    const { container } = render(<Reveal cards={cards} onClose={onClose}/>);

    expect(screen.getByRole("dialog", { name: "10장 카드 획득" })).toHaveClass("reveal-5", "batch");
    for (const card of cards) expect(screen.getByText(card.name)).toBeInTheDocument();
    expect([...container.querySelectorAll(".reveal-batch-card h3")].map(node => node.textContent)).toEqual([
      "카드 2",
      "카드 6",
      "카드 4",
      "카드 9",
      "카드 3",
      "카드 8",
      "카드 5",
      "카드 10",
      "카드 1",
      "카드 7",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "확인" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
