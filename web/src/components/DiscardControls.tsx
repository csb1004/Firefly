import { useState } from "react";
import { api, idempotencyKey } from "../api";
import type { Card } from "../types";

type DiscardPreview = {
  card_name: string;
  quantity: number;
  quantity_after: number;
  yp_before: number;
  yp_after: number;
  yp_change: number;
};

export function DiscardControls({ card, onDiscarded, onError }: { card: Card; onDiscarded: () => Promise<void> | void; onError: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [preview, setPreview] = useState<DiscardPreview>();
  const [busy, setBusy] = useState(false);
  const available = card.available_quantity ?? 0;

  function toggle() {
    setOpen(!open);
    setPreview(undefined);
    setQuantity(1);
  }
  async function loadPreview() {
    setBusy(true);
    try {
      setPreview(await api<DiscardPreview>("/api/collection/discard/preview", { method: "POST", body: JSON.stringify({ card_id: card.id, quantity }) }));
    } catch (error) { onError((error as Error).message); }
    finally { setBusy(false); }
  }
  async function confirmDiscard() {
    if (!preview) return;
    setBusy(true);
    try {
      await api("/api/collection/discard", { method: "POST", body: JSON.stringify({ card_id: card.id, quantity, idempotency_key: idempotencyKey("discard") }) }, true);
      setOpen(false); setPreview(undefined); await onDiscarded();
    } catch (error) { onError((error as Error).message); }
    finally { setBusy(false); }
  }

  return <><button className="card-more-button" aria-label={`${card.name} 카드 정리`} aria-expanded={open} onClick={toggle}>⋯</button>{open && <div className="inline-discard-panel"><label>버릴 수량<input aria-label={`${card.name} 버릴 수량`} type="number" min="1" max={available} value={quantity} onChange={event => { setQuantity(Number(event.target.value)); setPreview(undefined); }}/><small>사용 가능 {available}장</small></label>{preview ? <><div className="discard-preview"><span>버린 뒤 <b>{preview.quantity_after}장</b></span><span>YP <b>{preview.yp_before.toLocaleString()} → {preview.yp_after.toLocaleString()}</b></span><strong className={preview.yp_change < 0 ? "negative" : ""}>{preview.yp_change >= 0 ? "+" : ""}{preview.yp_change.toLocaleString()} YP</strong><small>도감 해금 기록은 유지됩니다.</small></div><button className="danger" disabled={busy} onClick={confirmDiscard}>버리기 확정</button></> : <button disabled={busy || quantity < 1 || quantity > available} onClick={loadPreview}>변화 확인</button>}</div>}</>;
}
