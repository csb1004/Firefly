import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(api).mockReset();
    vi.mocked(api).mockImplementation(async path => path === "/api/admin/sets" ? [] : {});
  });

  it("submits the visible default rarity when counting owned quantities", async () => {
    render(<AdminSetManager cards={[card]} />);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/admin/sets"));

    fireEvent.change(screen.getByLabelText("세트 이름"), { target: { value: "수량 세트" } });
    fireEvent.click(screen.getByText("테스트 카드").closest("label")!.querySelector("input")!);
    fireEvent.change(screen.getByLabelText("횟수 계산 대상"), { target: { value: "rarity" } });
    fireEvent.change(screen.getByLabelText("횟수 계산 방식"), { target: { value: "quantity" } });
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

  it("preserves every selected bonus rarity across multiple quantity effects", async () => {
    render(<AdminSetManager cards={[card]} />);
    await waitFor(() => expect(api).toHaveBeenCalledWith("/api/admin/sets"));

    fireEvent.change(screen.getByLabelText("세트 이름"), { target: { value: "다중 수량 세트" } });
    fireEvent.click(screen.getByText("테스트 카드").closest("label")!.querySelector("input")!);
    for (let index = 1; index < 5; index += 1) {
      fireEvent.click(screen.getByRole("button", { name: "+ 효과 추가" }));
    }

    for (let index = 0; index < 5; index += 1) {
      fireEvent.change(screen.getAllByLabelText("횟수 계산 방식")[index], { target: { value: "quantity" } });
      fireEvent.change(screen.getAllByLabelText("YP 증가 대상")[index], { target: { value: "rarity" } });
      fireEvent.change(screen.getAllByLabelText("YP 증가 대상 성급")[index], { target: { value: String(index + 1) } });
      fireEvent.change(screen.getAllByLabelText("YP 증가 방식")[index], { target: { value: "percent" } });
      fireEvent.change(screen.getAllByLabelText("증가 수치")[index], { target: { value: String((index + 1) * 10) } });
    }

    fireEvent.click(screen.getByRole("button", { name: "세트 저장" }));

    await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
    const saveCall = vi.mocked(api).mock.calls.find(call => call[1]?.method === "POST")!;
    const body = JSON.parse(String(saveCall[1]?.body));
    expect(body.effects.map((effect: { bonus_target_rarity: number | null }) => effect.bonus_target_rarity)).toEqual([1, 2, 3, 4, 5]);
  });

  it("normalizes a loaded empty rarity that is displayed as 1-star", async () => {
    vi.mocked(api).mockImplementation(async path => path === "/api/admin/sets" ? [{
      id: "set-1",
      name: "기존 세트",
      active: true,
      member_card_ids: [card.id],
      effects: [{
        target_scope: "set_members",
        target_rarity: null,
        target_card_ids: [],
        bonus_target_scope: "rarity",
        bonus_target_rarity: null,
        bonus_target_card_ids: [],
        count_mode: "quantity",
        bonus_type: "percent",
        value: 10,
        max_count: null,
      }],
    }] : {});

    render(<AdminSetManager cards={[card]} />);
    fireEvent.click(await screen.findByRole("button", { name: /기존 세트/ }));
    expect(screen.getByLabelText("YP 증가 대상 성급")).toHaveValue("1");

    fireEvent.click(screen.getByRole("button", { name: "세트 저장" }));

    await waitFor(() => expect(api).toHaveBeenCalledTimes(3));
    const saveCall = vi.mocked(api).mock.calls.find(call => call[1]?.method === "PUT")!;
    const body = JSON.parse(String(saveCall[1]?.body));
    expect(body.effects[0].bonus_target_rarity).toBe(1);
  });
});
