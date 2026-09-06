import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, openRealtime } from "./api";
import App from "./App";

vi.mock("./api", () => ({
  api: vi.fn(),
  idempotencyKey: vi.fn(() => "test-idempotency-key"),
  openRealtime: vi.fn(),
}));

const adminHarness = vi.hoisted(() => ({
  complete: undefined as undefined | ((result: any) => void),
}));

vi.mock("./components/AdminSeasonReset", () => ({
  AdminSeasonReset: ({ onCompleted }: { onCompleted: (result: any) => void }) => {
    adminHarness.complete = onCompleted;
    return null;
  },
}));

const me = {
  id: 1,
  discord_id: "1001",
  username: "admin",
  display_name: "관리자",
  avatar_url: "/admin.webp",
  warning_acknowledged: true,
  accepts_gifts: true,
  accepts_trades: true,
  is_admin: true,
};

const room = {
  id: "room-1",
  status: "negotiating",
  inviter_id: 1,
  invitee_id: 2,
  offer_version: 1,
  accepted: { "1": false, "2": false },
  offers: [],
  requests: [],
};

const invite = { ...room, status: "invited", inviter_id: 2, invitee_id: 1 };

const oldFeed = {
  id: "old-five-star",
  drawn_at: "2026-09-05T12:00:00+00:00",
  user_id: 2,
  username: "old-user",
  display_name: "이전 시즌 사용자",
  card_id: "old-card",
  card_name: "이전 시즌 5성",
};

const resetResult = {
  delete_counts: {},
  summary: { inventory_copies: 0, trade_records: 0, audit_records: 0 },
  preserved: {
    users: 2,
    cards: 5,
    card_sets: 1,
    rarity_settings: 5,
    image_cleanup: 0,
    draw_settings: { daily_draws: 10, new_user_bonus_tickets: 7 },
  },
  grant: { granted_users: 2, tickets_per_user: 7, total_tickets: 14 },
  completed_at: "2026-09-06T00:00:00+00:00",
  audit_id: "audit-1",
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(next => { resolve = next; });
  return { promise, resolve };
}

class FakeSocket extends EventTarget {
  close = vi.fn();
}

let feedCalls = 0;
let socket: FakeSocket;
let replaceSpy: ReturnType<typeof vi.spyOn>;
let pushSpy: ReturnType<typeof vi.spyOn>;

function countApiCalls(path: string) {
  return vi.mocked(api).mock.calls.filter(call => call[0] === path).length;
}

function installApiMocks() {
  vi.mocked(api).mockImplementation(async path => {
    if (path === "/api/auth/me") return me;
    if (path === "/api/feed/five-stars") {
      feedCalls += 1;
      return { items: feedCalls === 1 ? [oldFeed] : [] };
    }
    if (path === "/api/draw/status") {
      return { eligible: true, draws_remaining: 17, daily_remaining: 10, bonus_tickets: 7, four_remaining: 10, five_remaining: 90 };
    }
    if (path === "/api/probabilities/current") return { rarities: { 1: 100 }, cards: [] };
    if (path === "/api/probabilities") return { rarities: { 1: 100 }, cards: [] };
    if (path === "/api/trades/room-1") return room;
    if (path === "/api/collection/me" || path === "/api/users/2/collection") {
      return { user_id: path.includes("users") ? 2 : 1, total_yp: 0, active_sets: [], cards: [] };
    }
    if (path === "/api/admin/cards" || path === "/api/admin/sets" || path === "/api/sets") return [];
    if (path === "/api/admin/draw-settings") return { daily_draws: 10, new_user_bonus_tickets: 7 };
    return {};
  });
}

async function startAt(path: string) {
  history.replaceState({}, "", path);
  replaceSpy.mockClear();
  render(<App />);
  await waitFor(() => expect(openRealtime).toHaveBeenCalledTimes(1));
  return vi.mocked(openRealtime).mock.calls[0][0];
}

describe("season reset realtime behavior", () => {
  beforeEach(() => {
    cleanup();
    adminHarness.complete = undefined;
    feedCalls = 0;
    socket = new FakeSocket();
    vi.mocked(api).mockReset();
    vi.mocked(openRealtime).mockReset();
    vi.mocked(openRealtime).mockResolvedValue(socket as unknown as WebSocket);
    installApiMocks();
    replaceSpy = vi.spyOn(history, "replaceState");
    pushSpy = vi.spyOn(history, "pushState");
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    history.replaceState({}, "", "/");
  });

  it("replaces a stale trade route and reloads global data after season reset", async () => {
    const realtimeHandler = await startAt("/trade/room-1");
    await screen.findByRole("heading", { name: "실시간 거래" });
    await screen.findByText("이전 시즌 5성");

    act(() => realtimeHandler({ type: "season.reset" }));

    expect(location.pathname).toBe("/");
    expect(await screen.findByText("새 시즌이 시작되었습니다.")).toBeInTheDocument();
    expect(screen.queryByText("이전 시즌 5성")).not.toBeInTheDocument();
    await waitFor(() => expect(countApiCalls("/api/feed/five-stars")).toBe(2));
    await waitFor(() => expect(countApiCalls("/api/draw/status")).toBe(1));
    expect(replaceSpy).toHaveBeenCalledTimes(1);
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it("remounts the current draw page and clears stale invite and feed state", async () => {
    const realtimeHandler = await startAt("/");
    await screen.findByText("이전 시즌 5성");
    await waitFor(() => expect(countApiCalls("/api/draw/status")).toBe(1));

    act(() => realtimeHandler({ type: "trade.invited", room: invite }));
    expect(await screen.findByText("새 거래 초대가 도착했습니다.")).toBeInTheDocument();

    act(() => realtimeHandler({ type: "season.reset" }));

    expect(screen.queryByText("새 거래 초대가 도착했습니다.")).not.toBeInTheDocument();
    expect(screen.queryByText("이전 시즌 5성")).not.toBeInTheDocument();
    await waitFor(() => expect(countApiCalls("/api/draw/status")).toBe(2));
    await waitFor(() => expect(countApiCalls("/api/feed/five-stars")).toBe(2));
    expect(replaceSpy).not.toHaveBeenCalled();
    expect(pushSpy).not.toHaveBeenCalled();
  });

  it("ignores an initial five-star feed response that resolves after the season reset refresh", async () => {
    const initialFeed = deferred<{ items: typeof oldFeed[] }>();
    const baseApi = vi.mocked(api).getMockImplementation()!;
    let currentFeedCall = 0;
    vi.mocked(api).mockImplementation((path, options, csrf) => {
      if (path === "/api/feed/five-stars") {
        currentFeedCall += 1;
        feedCalls += 1;
        return currentFeedCall === 1 ? initialFeed.promise : Promise.resolve({ items: [] });
      }
      return baseApi(path, options, csrf);
    });

    const realtimeHandler = await startAt("/");
    await waitFor(() => expect(currentFeedCall).toBe(1));

    act(() => realtimeHandler({ type: "season.reset" }));
    await waitFor(() => expect(currentFeedCall).toBe(2));
    expect(await screen.findByText("새 시즌이 시작되었습니다.")).toBeInTheDocument();

    await act(async () => {
      initialFeed.resolve({ items: [oldFeed] });
      await initialFeed.promise;
    });

    expect(screen.queryByText("이전 시즌 5성")).not.toBeInTheDocument();
  });

  it.each(["websocket-first", "admin-result-first"])(
    "deduplicates %s completion and keeps the detailed administrator notice",
    async order => {
      const realtimeHandler = await startAt("/admin");
      await waitFor(() => expect(adminHarness.complete).toBeTypeOf("function"));
      await waitFor(() => expect(countApiCalls("/api/feed/five-stars")).toBe(1));

      act(() => {
        if (order === "websocket-first") {
          realtimeHandler({ type: "season.reset" });
          adminHarness.complete!(resetResult);
        } else {
          adminHarness.complete!(resetResult);
          realtimeHandler({ type: "season.reset" });
        }
      });

      expect(await screen.findByText("시즌 초기화 완료 · 2명에게 14장 지급")).toBeInTheDocument();
      await waitFor(() => expect(countApiCalls("/api/feed/five-stars")).toBe(2));
      await waitFor(() => expect(countApiCalls("/api/draw/status")).toBe(1));
      expect(replaceSpy).toHaveBeenCalledTimes(1);
      expect(pushSpy).not.toHaveBeenCalled();
    },
  );
});
