import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { Card } from "../types";
import { AdminSetManager } from "./AdminSetManager";

vi.mock("../api", () => ({ api: vi.fn() }));

const card: Card = {
  id: "card-1",
  name: "테스트 카드",
  rarity: 3,
  yp: 100,
  image_url: "/card.webp",
};

describe("AdminSetManager", () => {
  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(async path => path === "/api/admin/sets" ? [] : {});
  });

  it("submits the visible default rarity when counting owned quantities", async () => {
    render(<AdminSetManager cards={[card]} />);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/admin/sets"));

    fireEvent.change(screen.getByLabelText("세트 이름"), { target: { value: "수량 세트" } });
    fireEvent.click(screen.getByText("테스트 카드").closest("label")!.querySelector("input")!);
    fireEvent.change(screen.getByLabelText("적용 횟수 대상"), { target: { value: "rarity" } });
    fireEvent.change(screen.getByLabelText("적용 횟수"), { target: { value: "quantity" } });
    fireEvent.change(screen.getByLabelText("YP 증가 대상"), { target: { value: "rarity" } });
    expect(screen.getByLabelText("횟수 대상 성급")).toHaveValue("1");
    expect(screen.getByLabelText("YP 증가 대상 성급")).toHaveValue("1");

    fireEvent.click(screen.getByRole("button", { name: "세트 저장" }));

    await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
    const saveCall = vi.mocked(api).mock.calls.find(call => call[1]?.method === "POST")!;
    const body = JSON.parse(String(saveCall[1]?.body));
    expect(body.effects[0]).toMatchObject({
      target_scope: "rarity",
      target_rarity: 1,
      count_mode: "quantity",
      bonus_target_scope: "rarity",
      bonus_target_rarity: 1,
    });
  });
});
