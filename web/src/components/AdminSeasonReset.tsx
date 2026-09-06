import { useState } from "react";
import { api } from "../api";
import type { SeasonResetPreview, SeasonResetResult } from "../types";

const CONFIRMATION_TEXT = "영호 가챠 시즌 초기화";

const RESET_CATEGORIES = [
  ["inventory", "인벤토리"],
  ["catalog_unlocks", "도감 해금"],
  ["draw_states", "천장"],
  ["draw_wallets", "추가 뽑기권"],
  ["daily_draw_allowances", "일일 지급"],
  ["draw_batches", "뽑기 묶음"],
  ["draw_history", "뽑기 기록"],
  ["five_star_events", "5성 기록"],
  ["gifts", "선물"],
  ["discard_events", "버리기"],
  ["trade_rooms", "거래방"],
  ["trade_offers", "거래 제안"],
  ["trade_requests", "추가 요구"],
  ["notification_outbox", "알림"],
  ["websocket_tickets", "실시간 접속권"],
  ["probability_audit", "확률 감사"],
  ["admin_audit", "관리 감사"],
] as const;

function format(value: number) {
  return value.toLocaleString();
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

export function AdminSeasonReset({ onCompleted }: { onCompleted: (result: SeasonResetResult) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [preview, setPreview] = useState<SeasonResetPreview>();
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  function toggle() {
    if (expanded) setConfirmation("");
    setExpanded(value => !value);
  }

  async function loadPreview() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      setPreview(await api<SeasonResetPreview>("/api/admin/season-reset/preview"));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function executeReset() {
    if (busy || confirmation !== CONFIRMATION_TEXT) return;
    setBusy(true);
    setError("");
    let result: SeasonResetResult;
    try {
      result = await api<SeasonResetResult>("/api/admin/season-reset", {
        method: "POST",
        body: JSON.stringify({ confirmation: CONFIRMATION_TEXT }),
      }, true);
    } catch (caught) {
      setError(errorMessage(caught));
      return;
    } finally {
      setBusy(false);
    }
    onCompleted(result);
  }

  return (
    <section className="season-reset-zone">
      <button
        type="button"
        className="season-reset-toggle danger"
        aria-expanded={expanded}
        onClick={toggle}
      >
        {expanded ? "위험 구역 닫기" : "위험 구역 열기"}
      </button>

      {expanded && (
        <div className="season-reset-content">
          <div>
            <p className="eyebrow">DANGER ZONE</p>
            <h2>시즌 초기화</h2>
            <p>로그인 정보와 관리자 설정은 유지하고, 모든 플레이어의 진행도와 활동 기록을 삭제합니다.</p>
          </div>

          <button type="button" disabled={busy} onClick={loadPreview}>
            {busy && !preview ? "확인 중" : "초기화 대상 확인"}
          </button>

          {error && <p className="season-reset-status error" role="alert">{error}</p>}

          {preview && (
            <>
              <section className="season-reset-counts" aria-labelledby="season-reset-delete-title">
                <h3 id="season-reset-delete-title">초기화 대상</h3>
                <div className="season-reset-summary">
                  <strong>인벤토리 카드 총 {format(preview.summary.inventory_copies)}장</strong>
                  <strong>거래 기록 총 {format(preview.summary.trade_records)}건</strong>
                  <strong>과거 감사 기록 총 {format(preview.summary.audit_records)}건</strong>
                </div>
                <ul>
                  {RESET_CATEGORIES.map(([key, label]) => (
                    <li key={key}>{label} {format(preview.delete_counts[key] ?? 0)}건</li>
                  ))}
                </ul>
              </section>

              <section className="season-reset-preserved" aria-labelledby="season-reset-preserved-title">
                <h3 id="season-reset-preserved-title">보존 대상</h3>
                <p>Discord 계정과 현재 로그인 상태도 그대로 유지됩니다.</p>
                <ul>
                  <li>사용자 {format(preview.preserved.users)}명</li>
                  <li>카드 {format(preview.preserved.cards)}개</li>
                  <li>카드 세트 {format(preview.preserved.card_sets)}개</li>
                  <li>등급 확률 설정 {format(preview.preserved.rarity_settings)}개</li>
                  <li>이미지 정리 예약 {format(preview.preserved.image_cleanup)}건</li>
                  <li>매일 기본 지급 {format(preview.preserved.draw_settings.daily_draws)}회</li>
                  <li>신규 사용자 혜택 {format(preview.preserved.draw_settings.new_user_bonus_tickets)}장</li>
                </ul>
              </section>

              <section className="season-reset-preserved" aria-labelledby="season-reset-grant-title">
                <h3 id="season-reset-grant-title">초기화 후 재지급</h3>
                <ul>
                  <li>대상 사용자 {format(preview.grant.eligible_users)}명</li>
                  <li>사용자당 추가 뽑기권 {format(preview.grant.tickets_per_user)}장</li>
                  <li>총 {format(preview.grant.total_tickets)}장 재지급</li>
                </ul>
              </section>

              <div className="season-reset-confirmation">
                <strong>되돌릴 수 없습니다</strong>
                <p>계속하려면 아래에 <b>{CONFIRMATION_TEXT}</b>를 정확히 입력하세요.</p>
                <label>
                  확인 문구
                  <input
                    value={confirmation}
                    onChange={event => setConfirmation(event.target.value)}
                    autoComplete="off"
                    placeholder={CONFIRMATION_TEXT}
                  />
                </label>
                <button
                  type="button"
                  className="danger"
                  disabled={busy || confirmation !== CONFIRMATION_TEXT}
                  onClick={executeReset}
                >
                  {busy ? "초기화 진행 중" : "시즌 초기화 실행"}
                </button>
                {busy && <p className="season-reset-status" role="status">시즌 초기화를 진행하고 있습니다.</p>}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
