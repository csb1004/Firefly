import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import type { SeasonResetPreview, SeasonResetResult } from "../types";
import { AdminSeasonReset } from "./AdminSeasonReset";

vi.mock("../api", () => ({ api: vi.fn() }));

const preview: SeasonResetPreview = {
  delete_counts: {
    inventory: 1,
    catalog_unlocks: 2,
    draw_states: 3,
    draw_wallets: 4,
    daily_draw_allowances: 5,
    draw_batches: 6,
    draw_history: 7,
    five_star_events: 8,
    gifts: 9,
    discard_events: 10,
    trade_rooms: 11,
    trade_offers: 12,
    trade_requests: 13,
    notification_outbox: 14,
    websocket_tickets: 15,
    probability_audit: 16,
    admin_audit: 17,
  },
  summary: {
    inventory_copies: 123,
    trade_records: 36,
    audit_records: 33,
  },
  preserved: {
    users: 7,
    cards: 8,
    card_sets: 3,
    rarity_settings: 5,
    image_cleanup: 2,
    draw_settings: {
      daily_draws: 10,
      new_user_bonus_tickets: 20,
    },
  },
  grant: {
    eligible_users: 7,
    tickets_per_user: 20,
    total_tickets: 140,
  },
};

const result: SeasonResetResult = {
  ...preview,
  grant: {
    granted_users: 7,
    tickets_per_user: 20,
    total_tickets: 140,
  },
  completed_at: "2026-09-06T05:00:00+00:00",
  audit_id: "audit-1",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}

async function loadPreview(onCompleted = vi.fn()) {
  vi.mocked(api).mockResolvedValueOnce(preview);
  render(<AdminSeasonReset onCompleted={onCompleted} />);
  fireEvent.click(screen.getByRole("button", { name: "위험 구역 열기" }));
  fireEvent.click(screen.getByRole("button", { name: "초기화 대상 확인" }));
  await screen.findByText("되돌릴 수 없습니다");
  return onCompleted;
}

describe("AdminSeasonReset", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.mocked(api).mockReset();
  });

  it("keeps destructive controls hidden and does not fetch until preview is requested", async () => {
    vi.mocked(api).mockResolvedValue(preview);
    render(<AdminSeasonReset onCompleted={vi.fn()} />);

    const toggle = screen.getByRole("button", { name: "위험 구역 열기" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByLabelText("확인 문구")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "초기화 대상 확인" })).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();

    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: "위험 구역 닫기" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByLabelText("확인 문구")).not.toBeInTheDocument();
    expect(api).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "초기화 대상 확인" }));

    await screen.findByText("되돌릴 수 없습니다");
    expect(api).toHaveBeenCalledWith("/api/admin/season-reset/preview");
  });

  it("shows every reset category, preserved setting, and grant impact with Korean labels", async () => {
    await loadPreview();

    const resetSection = screen.getByRole("region", { name: "초기화 대상" });
    const expectedResetRows = [
      "인벤토리 1건",
      "도감 해금 2건",
      "천장 3건",
      "추가 뽑기권 4건",
      "일일 지급 5건",
      "뽑기 묶음 6건",
      "뽑기 기록 7건",
      "5성 기록 8건",
      "선물 9건",
      "버리기 10건",
      "거래방 11건",
      "거래 제안 12건",
      "추가 요구 13건",
      "알림 14건",
      "실시간 접속권 15건",
      "확률 감사 16건",
      "관리 감사 17건",
    ];
    for (const row of expectedResetRows) {
      expect(within(resetSection).getByText(row)).toBeInTheDocument();
    }
    expect(within(resetSection).getByText("인벤토리 카드 총 123장")).toBeInTheDocument();
    expect(within(resetSection).getByText("거래 기록 총 36건")).toBeInTheDocument();
    expect(within(resetSection).getByText("과거 감사 기록 총 33건")).toBeInTheDocument();

    const preservedSection = screen.getByRole("region", { name: "보존 대상" });
    for (const row of [
      "사용자 7명",
      "카드 8개",
      "카드 세트 3개",
      "등급 확률 설정 5개",
      "이미지 정리 예약 2건",
      "매일 기본 지급 10회",
      "신규 사용자 혜택 20장",
    ]) {
      expect(within(preservedSection).getByText(row)).toBeInTheDocument();
    }

    const grantSection = screen.getByRole("region", { name: "초기화 후 재지급" });
    expect(within(grantSection).getByText("대상 사용자 7명")).toBeInTheDocument();
    expect(within(grantSection).getByText("사용자당 추가 뽑기권 20장")).toBeInTheDocument();
    expect(within(grantSection).getByText("총 140장 재지급")).toBeInTheDocument();
  });

  it("enables execution only when the exact confirmation phrase is entered", async () => {
    await loadPreview();
    const input = screen.getByLabelText("확인 문구");
    const execute = screen.getByRole("button", { name: "시즌 초기화 실행" });

    expect(execute).toBeDisabled();
    fireEvent.change(input, { target: { value: "시즌 초기화" } });
    expect(execute).toBeDisabled();
    fireEvent.change(input, { target: { value: "영호 가챠 시즌 초기화" } });
    expect(execute).toBeEnabled();
  });

  it("sends one CSRF-protected reset request during rapid clicks and completes once", async () => {
    const operation = deferred<SeasonResetResult>();
    const onCompleted = await loadPreview();
    vi.mocked(api).mockImplementationOnce(() => operation.promise);
    fireEvent.change(screen.getByLabelText("확인 문구"), { target: { value: "영호 가챠 시즌 초기화" } });
    const execute = screen.getByRole("button", { name: "시즌 초기화 실행" });

    fireEvent.click(execute);
    fireEvent.click(execute);

    expect(screen.getByRole("button", { name: "초기화 진행 중" })).toBeDisabled();
    expect(vi.mocked(api).mock.calls.filter(call => call[0] === "/api/admin/season-reset")).toHaveLength(1);
    expect(api).toHaveBeenCalledWith("/api/admin/season-reset", {
      method: "POST",
      body: JSON.stringify({ confirmation: "영호 가챠 시즌 초기화" }),
    }, true);

    operation.resolve(result);
    await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
    expect(onCompleted).toHaveBeenCalledWith(result);
  });

  it("keeps the preview visible and reports the server error when execution fails", async () => {
    await loadPreview();
    vi.mocked(api).mockRejectedValueOnce(new Error("시즌 초기화가 이미 진행 중입니다."));
    fireEvent.change(screen.getByLabelText("확인 문구"), { target: { value: "영호 가챠 시즌 초기화" } });

    fireEvent.click(screen.getByRole("button", { name: "시즌 초기화 실행" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("시즌 초기화가 이미 진행 중입니다.");
    expect(screen.getByRole("region", { name: "초기화 대상" })).toBeInTheDocument();
    expect(screen.getByText("인벤토리 카드 총 123장")).toBeInTheDocument();
    expect(screen.getByLabelText("확인 문구")).toHaveValue("영호 가챠 시즌 초기화");
  });

  it("clears the confirmation phrase whenever the danger zone is collapsed", async () => {
    await loadPreview();
    fireEvent.change(screen.getByLabelText("확인 문구"), { target: { value: "영호 가챠 시즌 초기화" } });

    fireEvent.click(screen.getByRole("button", { name: "위험 구역 닫기" }));
    fireEvent.click(screen.getByRole("button", { name: "위험 구역 열기" }));

    expect(screen.getByLabelText("확인 문구")).toHaveValue("");
    expect(screen.getByRole("button", { name: "시즌 초기화 실행" })).toBeDisabled();
  });
});
