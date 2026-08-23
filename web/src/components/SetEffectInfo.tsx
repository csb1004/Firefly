import { useEffect } from "react";
import type { SetDefinition } from "../types";
import { Stars } from "./CardTile";

export function describeSetEffect(effect: SetDefinition["effects"][number]) {
  function targetLabel(scope: typeof effect.target_scope, rarity: number | null, cards: typeof effect.target_cards) {
    if (scope === "set_members") return "세트 구성 카드";
    if (scope === "selected_cards") return cards.map(card => card.name).join(" · ") || "선택한 카드";
    if (scope === "rarity") return `${rarity}성 카드`;
    return "보유 중인 모든 카드";
  }
  const countTarget = targetLabel(effect.target_scope, effect.target_rarity, effect.target_cards);
  const bonusTarget = targetLabel(effect.bonus_target_scope, effect.bonus_target_rarity, effect.bonus_target_cards);

  let condition: string;
  if (effect.count_mode === "once") {
    if (effect.target_scope === "set_members") condition = "세트 완성 시";
    else if (effect.target_scope === "collection") condition = "보유 카드가 있을 때";
    else condition = `${countTarget} 보유 시`;
  }
  else if (effect.count_mode === "distinct") condition = `${countTarget} 종류당`;
  else condition = `${countTarget} 1장당`;

  const value = Number(effect.value).toLocaleString("ko-KR", { maximumFractionDigits: 4 });
  const bonus = effect.bonus_type === "fixed" ? `${bonusTarget}의 YP가 ${value} 증가` : `${bonusTarget}의 최종 YP가 ${value}% 증가`;
  return `${condition}, ${bonus}${effect.max_count ? ` · 최대 ${effect.max_count}회` : ""}`;
}

export function SetEffectList({ sets, progress = false, activeSetNames }: { sets: SetDefinition[]; progress?: boolean; activeSetNames?: string[] }) {
  const activeNames = activeSetNames ? new Set(activeSetNames) : null;
  return <div className="set-effect-cards">{sets.map(cardSet => { const active = activeNames ? activeNames.has(cardSet.name) : cardSet.completed; return <article className={`set-effect-card ${active ? "completed" : "incomplete"}`} key={cardSet.id}><header><div><p className="eyebrow">SET EFFECT</p><h3>{cardSet.name}</h3></div>{progress && <span>{active ? "적용 중" : `${cardSet.owned_member_count}/${cardSet.required_member_count}`}</span>}</header><div className="set-members">{cardSet.member_cards.map(card => <span className={`rarity-${card.rarity}`} key={card.id}><b>{card.name}</b><Stars rarity={card.rarity}/></span>)}</div><ul>{cardSet.effects.map((effect, index) => <li key={effect.id ?? index}>{describeSetEffect(effect)}</li>)}</ul></article>; })}</div>;
}

export function ActiveSetSummary({ sets, activeSetNames, onOpen }: { sets: SetDefinition[]; activeSetNames: string[]; onOpen: () => void }) {
  const activeNames = new Set(activeSetNames);
  const activeSets = sets.filter(cardSet => activeNames.has(cardSet.name));
  const hiddenCount = Math.max(0, activeSets.length - 3);
  return <button className="active-set-summary" aria-label="전체 세트 효과 보기" onClick={onOpen}>
    <span className="active-set-summary-copy"><small>ACTIVE SETS</small><strong>{activeSets.length}개 적용 중</strong></span>
    <span className="active-set-summary-chips">{activeSets.length ? <>{activeSets.slice(0, 3).map(cardSet => <b key={cardSet.id}>✦ {cardSet.name}</b>)}{hiddenCount > 0 && <b>+{hiddenCount}</b>}</> : <em>현재 적용 중인 세트가 없습니다.</em>}</span>
    <span className="active-set-summary-cta">전체 보기 <i aria-hidden="true">→</i></span>
  </button>;
}

export function ActiveSetModal({ sets, activeSetNames, totalYp, onClose }: { sets: SetDefinition[]; activeSetNames: string[]; totalYp: number; onClose: () => void }) {
  const activeNames = new Set(activeSetNames);
  const activeSets = sets.filter(cardSet => activeNames.has(cardSet.name));
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    addEventListener("keydown", closeOnEscape);
    return () => removeEventListener("keydown", closeOnEscape);
  }, [onClose]);
  return <div className="set-info-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section className="set-info-dialog" role="dialog" aria-modal="true" aria-labelledby="set-info-title"><header><div><p className="eyebrow">ACTIVE SETS</p><h2 id="set-info-title">적용 중인 세트 효과</h2></div><button className="set-info-close" aria-label="닫기" onClick={onClose}>×</button></header><p className="set-info-total">현재 최종 YP <strong>{totalYp.toLocaleString()}</strong></p>{activeSets.length ? <SetEffectList sets={activeSets}/> : <div className="empty">현재 완성되어 적용 중인 세트가 없습니다.</div>}</section></div>;
}
