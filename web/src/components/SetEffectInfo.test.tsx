import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SetDefinition } from "../types";
import { ActiveSetModal, describeSetEffect } from "./SetEffectInfo";

const activeSet: SetDefinition = {
  id: "set-1",
  name: "별빛 세트",
  completed: true,
  owned_member_count: 1,
  required_member_count: 1,
  member_cards: [{ id: "card-1", name: "별빛 카드", rarity: 5 }],
  effects: [{
    id: "effect-1",
    target_scope: "rarity",
    target_rarity: 1,
    target_cards: [],
    count_mode: "quantity",
    bonus_type: "fixed",
    value: 50,
    max_count: 3,
  }],
};

describe("set effect information", () => {
  it("turns a configurable effect into a readable Korean summary", () => {
    expect(describeSetEffect(activeSet.effects[0])).toBe("1성 카드 1장당 YP 50 증가 · 최대 3회");
  });

  it("describes a one-time whole-collection effect without repeating ownership", () => {
    expect(describeSetEffect({
      ...activeSet.effects[0],
      target_scope: "collection",
      target_rarity: null,
      count_mode: "once",
      bonus_type: "percent",
      value: 20,
      max_count: null,
    })).toBe("세트 완성 시 보유 중인 모든 카드의 최종 YP 20% 증가");
  });

  it("shows only completed sets in the inventory information dialog", () => {
    const close = vi.fn();
    render(<ActiveSetModal sets={[activeSet, {...activeSet, id: "set-2", name: "미완성 세트", completed: false}]} totalYp={1250} onClose={close}/>);
    expect(screen.getByRole("dialog", { name: "적용 중인 세트 효과" })).toBeInTheDocument();
    expect(screen.getByText("별빛 세트")).toBeInTheDocument();
    expect(screen.queryByText("미완성 세트")).not.toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
  });
});
