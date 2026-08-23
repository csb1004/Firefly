import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SetDefinition } from "../types";
import { ActiveSetModal, ActiveSetSummary, describeSetEffect, SetEffectList } from "./SetEffectInfo";

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
    bonus_target_scope: "set_members",
    bonus_target_rarity: null,
    bonus_target_cards: [],
    count_mode: "quantity",
    bonus_type: "fixed",
    value: 50,
    max_count: 3,
  }],
};

describe("set effect information", () => {
  afterEach(cleanup);

  it("turns a configurable effect into a readable Korean summary", () => {
    expect(describeSetEffect(activeSet.effects[0])).toBe("1성 카드 1장당, 세트 구성 카드의 YP가 50 증가 · 최대 3회");
  });

  it("describes a one-time whole-collection effect without repeating ownership", () => {
    expect(describeSetEffect({
      ...activeSet.effects[0],
      target_scope: "collection",
      target_rarity: null,
      bonus_target_scope: "collection",
      bonus_target_rarity: null,
      count_mode: "once",
      bonus_type: "percent",
      value: 20,
      max_count: null,
    })).toBe("보유 카드가 있을 때, 보유 중인 모든 카드의 최종 YP가 20% 증가");
  });

  it("shows the sets reported as active even when a distinct effect is partially unlocked", () => {
    const close = vi.fn();
    const partialSet = {...activeSet, id: "set-2", name: "부분 적용 세트", completed: false};
    render(<ActiveSetModal sets={[activeSet, partialSet]} activeSetNames={[partialSet.name]} totalYp={1250} onClose={close}/>);
    expect(screen.getByRole("dialog", { name: "적용 중인 세트 효과" })).toBeInTheDocument();
    expect(screen.queryByText("별빛 세트")).not.toBeInTheDocument();
    expect(screen.getByText("부분 적용 세트")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalledOnce();
  });

  it("shows only active sets in the compact catalog summary and opens the archive", () => {
    const open = vi.fn();
    const partialSet = {...activeSet, id: "set-2", name: "부분 적용 세트", completed: false};
    render(<ActiveSetSummary sets={[activeSet, partialSet]} activeSetNames={[partialSet.name]} onOpen={open}/>);

    expect(screen.getByRole("button", { name: "전체 세트 효과 보기" })).toHaveTextContent("1개 적용 중");
    expect(screen.getByRole("button", { name: "전체 세트 효과 보기" })).toHaveTextContent("부분 적용 세트");
    expect(screen.queryByText("별빛 세트")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "전체 세트 효과 보기" }));
    expect(open).toHaveBeenCalledOnce();
  });

  it("marks a partially completed set as active when one of its effects is running", () => {
    const partialSet = {...activeSet, id: "set-2", name: "부분 적용 세트", completed: false, owned_member_count: 1, required_member_count: 3};
    render(<SetEffectList sets={[partialSet]} progress activeSetNames={[partialSet.name]}/>);

    expect(screen.getByText("적용 중")).toBeInTheDocument();
    expect(screen.queryByText("1/3")).not.toBeInTheDocument();
  });
});
