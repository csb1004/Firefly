import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CardTile } from "./CardTile";
import { Reveal } from "./Reveal";

const card = { id:"1", name:"히메코", rarity:5, yp:900, image_url:"/himeko.webp", quantity:3 };

describe("card presentation", () => {
  it("shows rarity with vector stars, border class, YP and duplicate quantity", () => {
    const { container } = render(<CardTile card={card} />);
    expect(screen.getByRole("img", { name:"히메코 카드" })).toBeInTheDocument();
    expect(screen.getByLabelText("5성").querySelectorAll("svg")).toHaveLength(5);
    expect(screen.getByText("900 YP")).toBeInTheDocument();
    expect(screen.getByText("×3")).toBeInTheDocument();
    expect(container.querySelector(".rarity-5")).toBeInTheDocument();
  });

  it("lets the player skip a five-star reveal", () => {
    const close = vi.fn();
    render(<Reveal card={card} onClose={close} />);
    fireEvent.click(screen.getByRole("button", { name:"건너뛰기" }));
    expect(close).toHaveBeenCalledOnce();
  });

  it("opens card details with pointer or keyboard activation", () => {
    const open = vi.fn();
    render(<CardTile card={card} onClick={open} />);
    const tile = screen.getByRole("button", { name:"히메코 카드 상세 보기" });
    fireEvent.click(tile);
    fireEvent.keyDown(tile, { key:"Enter" });
    fireEvent.keyDown(tile, { key:" " });
    expect(open).toHaveBeenCalledTimes(3);
  });
});
