import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Card } from "../types";
import { AdminCardControls } from "./AdminCardControls";

const card: Card = {
  id: "card-1",
  name: "별빛 카드",
  rarity: 5,
  yp: 500,
  image_url: "/card.webp",
  weight: 1,
  active: true,
};

describe("AdminCardControls", () => {
  it("reveals inline card editing only after pressing manage", () => {
    const view = render(<AdminCardControls card={card} open={false} onToggle={vi.fn()} onSave={vi.fn()} onToggleActive={vi.fn()} onImage={vi.fn()} onRemoved={vi.fn()} onError={vi.fn()}/>);

    expect(screen.queryByLabelText("이름")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "영구 삭제" })).not.toBeInTheDocument();

    view.rerender(<AdminCardControls card={card} open onToggle={vi.fn()} onSave={vi.fn()} onToggleActive={vi.fn()} onImage={vi.fn()} onRemoved={vi.fn()} onError={vi.fn()}/>);

    expect(screen.getByLabelText("이름")).toHaveValue("별빛 카드");
    expect(screen.getByRole("button", { name: "정보 저장" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "영구 삭제" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
  });
});
