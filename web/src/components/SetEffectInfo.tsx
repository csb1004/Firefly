import { useEffect } from "react";
import type { SetDefinition } from "../types";
import { Stars } from "./CardTile";

export function describeSetEffect(effect: SetDefinition["effects"][number]) {
  function selectedCardLabel(cards: typeof effect.target_cards) {
    const names = cards.map(card => card.name).join(" · ");
    return names ? `선택한 카드(${names})` : "선택한 카드";
  }

  function countTargetLabel() {
    if (effect.target_scope === "set_members") return "보유 중인 세트 구성 카드";
    if (effect.target_scope === "selected_cards") return `보유 중인 ${selectedCardLabel(effect.target_cards)}`;
    if (effect.target_scope === "rarity") return `보유 중인 ${effect.target_rarity}성 카드`;
    return "보유 카드";
  }

  function bonusTargetLabel() {
    if (effect.bonus_target_scope === "set_members") return "보유 중인 세트 구성 카드";
    if (effect.bonus_target_scope === "selected_cards") return `${selectedCardLabel(effect.bonus_target_cards)} 중 보유 카드`;
    if (effect.bonus_target_scope === "rarity") return `보유 중인 ${effect.bonus_target_rarity}성 카드`;
    return "보유 중인 모든 카드";
  }

  let condition: string;
  if (effect.count_mode === "once") {
    if (effect.target_scope === "set_members" || effect.target_scope === "collection") condition = "세트 완성 시";
    else {
      const target = effect.target_scope === "rarity"
        ? `${effect.target_rarity}성 카드`
        : selectedCardLabel(effect.target_cards);
      condition = `세트 완성 후, ${target}를 1장 이상 보유하면`;
    }
  }
  else if (effect.count_mode === "distinct") condition = `${countTargetLabel()} 종류당`;
  else condition = `세트 완성 후, ${countTargetLabel()} 1장당`;

  const value = Number(effect.value).toLocaleString("ko-KR", { maximumFractionDigits: 4 });
  const bonusTarget = bonusTargetLabel();
  const bonus = effect.bonus_type === "fixed" ? `${bonusTarget} 각각의 YP가 ${value} 증가` : `${bonusTarget} 각각의 최종 YP가 ${value}% 증가`;
  return `${condition}, ${bonus}${effect.max_count ? ` · 최대 ${effect.max_count}회 적용` : ""}`;
}

function formatYp(value: number) {
  return Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 });
}

function SetBonusDetails({ bonus }: { bonus: SetDefinition["yp_bonus"] }) {
  if (!bonus.cards.length) return null;
  return <details className="set-bonus-details">
    <summary><span>자세히</span><small>{bonus.cards.length}종</small></summary>
    <div className="set-bonus-card-list">{bonus.cards.map(card => <div className="set-bonus-card" key={card.card_id}>
      <div className="set-bonus-card-head"><span className={`rarity-${card.rarity}`}><b>{card.card_name}</b><Stars rarity={card.rarity}/></span><small>보유 {card.quantity}장</small></div>
      <div className="set-bonus-card-values"><span>기본 <b>{formatYp(card.base_yp)} YP</b></span><span>이 세트 적용 <b>{formatYp(card.base_yp + card.total_bonus)} YP</b></span></div>
      <p>{card.fixed_bonus > 0 && <span>고정 +{formatYp(card.fixed_bonus)}</span>}{card.percent_bonus > 0 && <span>% 효과 +{formatYp(card.percent_bonus)}</span>}<strong>총 +{formatYp(card.total_bonus)} YP</strong></p>
    </div>)}</div>
  </details>;
}

export function SetEffectList({ sets, progress = false, activeSetNames }: { sets: SetDefinition[]; progress?: boolean; activeSetNames?: string[] }) {
  const activeNames = activeSetNames ? new Set(activeSetNames) : null;
  return <div className="set-effect-cards">{sets.map(cardSet => {
    const active = activeNames ? activeNames.has(cardSet.name) : cardSet.completed;
    const bonus = cardSet.yp_bonus ?? { total: 0, cards: [] };
    return <article className={`set-effect-card ${active ? "completed" : "incomplete"}`} key={cardSet.id}>
      <header><div><p className="eyebrow">SET EFFECT</p><h3>{cardSet.name}</h3></div><div className="set-effect-status">
        {progress && <span className="set-status-badge">{active ? "적용 중" : `${cardSet.owned_member_count}/${cardSet.required_member_count}`}</span>}
        <span className={`set-effect-gain ${bonus.total > 0 ? "positive" : "zero"}`}><small>세트 효과</small><strong>+{formatYp(bonus.total)} YP</strong></span>
      </div></header>
      <div className="set-members">{cardSet.member_cards.map(card => <span className={`rarity-${card.rarity}`} key={card.id}><b>{card.name}</b><Stars rarity={card.rarity}/></span>)}</div>
      <ul>{cardSet.effects.map((effect, index) => <li key={effect.id ?? index}>{describeSetEffect(effect)}</li>)}</ul>
      <SetBonusDetails bonus={bonus}/>
    </article>;
  })}</div>;
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
  return <div className="set-info-overlay" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section className="set-info-dialog" role="dialog" aria-modal="true" aria-labelledby="set-info-title"><header><div><p className="eyebrow">ACTIVE SETS</p><h2 id="set-info-title">적용 중인 세트 효과</h2></div><button className="set-info-close" aria-label="닫기" onClick={onClose}>×</button></header><p className="set-info-total">현재 최종 YP <strong>{totalYp.toLocaleString()}</strong></p>{activeSets.length ? <SetEffectList sets={activeSets}/> : <div className="empty">현재 적용 중인 세트 효과가 없습니다.</div>}</section></div>;
}
