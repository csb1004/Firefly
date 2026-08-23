import { useEffect, useState } from "react";
import { api } from "../api";
import type { Card, CardSet, SetEffect } from "../types";
import { Stars } from "./CardTile";

const blankEffect = (): SetEffect => ({ target_scope: "set_members", target_rarity: null, target_card_ids: [], bonus_target_scope: "set_members", bonus_target_rarity: null, bonus_target_card_ids: [], count_mode: "once", bonus_type: "fixed", value: 50, max_count: null });
type DraftSet = Omit<CardSet, "id"> & { id?: string };
const blankSet = (): DraftSet => ({ name: "", active: true, member_card_ids: [], effects: [blankEffect()] });

export function AdminSetManager({ cards }: { cards: Card[] }) {
  const [sets, setSets] = useState<CardSet[]>([]);
  const [draft, setDraft] = useState<DraftSet>(blankSet());
  const [message, setMessage] = useState("");
  const load = () => api<CardSet[]>("/api/admin/sets").then(setSets);
  useEffect(() => { load().catch(error => setMessage(error.message)); }, []);

  function toggleMember(cardId: string) {
    const member_card_ids = draft.member_card_ids.includes(cardId) ? draft.member_card_ids.filter(id => id !== cardId) : [...draft.member_card_ids, cardId];
    setDraft({...draft, member_card_ids});
  }
  function updateEffect(index: number, patch: Partial<SetEffect>) {
    setDraft({...draft, effects: draft.effects.map((effect, position) => position === index ? {...effect, ...patch} : effect)});
  }
  function toggleTarget(index: number, cardId: string, kind: "count" | "bonus") {
    const effect = draft.effects[index];
    const field = kind === "count" ? "target_card_ids" : "bonus_target_card_ids";
    const cardIds = effect[field].includes(cardId) ? effect[field].filter(id => id !== cardId) : [...effect[field], cardId];
    updateEffect(index, { [field]: cardIds });
  }
  function useTemplate(kind: "rarity" | "members" | "collection") {
    const effect = blankEffect();
    if (kind === "rarity") Object.assign(effect, { target_scope: "set_members", count_mode: "once", bonus_target_scope: "rarity", bonus_target_rarity: 1, bonus_type: "fixed", value: 50 });
    if (kind === "members") Object.assign(effect, { target_scope: "set_members", count_mode: "once", bonus_target_scope: "set_members", bonus_type: "percent", value: 5 });
    if (kind === "collection") Object.assign(effect, { target_scope: "set_members", count_mode: "once", bonus_target_scope: "collection", bonus_type: "fixed", value: 10 });
    setDraft({...draft, effects: [effect]});
  }
  async function save() {
    try {
      const path = draft.id ? `/api/admin/sets/${draft.id}` : "/api/admin/sets";
      const body = {
        ...draft,
        effects: draft.effects.map(effect => ({
          ...effect,
          target_rarity: effect.target_scope === "rarity" ? effect.target_rarity ?? 1 : null,
          bonus_target_rarity: effect.bonus_target_scope === "rarity" ? effect.bonus_target_rarity ?? 1 : null,
        })),
      };
      await api(path, { method: draft.id ? "PUT" : "POST", body: JSON.stringify(body) }, true);
      setMessage("세트 효과를 저장했습니다."); setDraft(blankSet()); await load();
    } catch (error) { setMessage((error as Error).message); }
  }
  async function remove(item: CardSet) {
    if (!confirm(`${item.name} 세트를 삭제할까요?`)) return;
    try { await api(`/api/admin/sets/${item.id}`, { method: "DELETE" }, true); setDraft(blankSet()); await load(); }
    catch (error) { setMessage((error as Error).message); }
  }

  return <section className="admin-set-section">
    <div className="section-title"><div><p className="eyebrow">SET BONUS</p><h2>세트 효과 관리</h2></div></div>
    {message && <p className="notice">{message}</p>}
    <div className="set-manager-grid">
      <aside className="panel set-list">
        <button className="primary-button" onClick={() => setDraft(blankSet())}>+ 새 세트</button>
        {sets.map(item => <button key={item.id} onClick={() => setDraft({...item, effects: item.effects.map(effect => ({...effect}))})}><b>{item.name}</b><small>{item.active ? "사용 중" : "꺼짐"} · 효과 {item.effects.length}개</small></button>)}
      </aside>
      <div className="panel set-editor">
        <div className="set-editor-head"><label>세트 이름<input value={draft.name} maxLength={100} onChange={event => setDraft({...draft, name: event.target.value})}/></label><label className="catalog-check"><input type="checkbox" checked={draft.active} onChange={event => setDraft({...draft, active: event.target.checked})}/>효과 활성화</label></div>
        <h3>완성에 필요한 카드</h3>
        <div className="card-check-grid">{cards.map(card => <label className={`rarity-${card.rarity}`} key={card.id}><input type="checkbox" checked={draft.member_card_ids.includes(card.id)} onChange={() => toggleMember(card.id)}/><img src={card.image_url} alt=""/><span>{card.name}<Stars rarity={card.rarity}/></span></label>)}</div>
        <div className="template-row"><span>빠른 템플릿</span><button onClick={() => useTemplate("rarity")}>완성 시 1성 카드 +50 YP</button><button onClick={() => useTemplate("members")}>완성 시 세트 카드 +5%</button><button onClick={() => useTemplate("collection")}>완성 시 전체 카드 +10 YP</button></div>
        <div className="effect-list">{draft.effects.map((effect, index) => <div className="effect-editor" key={index}>
          <div className="effect-heading"><b>효과 {index + 1}</b><button className="danger" disabled={draft.effects.length === 1} onClick={() => setDraft({...draft, effects: draft.effects.filter((_, position) => position !== index)})}>삭제</button></div>
          <div className="effect-fields">
            <label>횟수 계산 대상<select value={effect.target_scope} onChange={event => { const target_scope = event.target.value as SetEffect["target_scope"]; updateEffect(index, { target_scope, target_rarity: target_scope === "rarity" ? effect.target_rarity ?? 1 : null }); }}><option value="set_members">세트 구성 카드</option><option value="selected_cards">직접 선택한 카드</option><option value="rarity">특정 성급 카드</option><option value="collection">보유 중인 모든 카드</option></select></label>
            {effect.target_scope === "rarity" && <label>횟수 대상 성급<select value={effect.target_rarity ?? 1} onChange={event => updateEffect(index, { target_rarity: Number(event.target.value) })}>{[1,2,3,4,5].map(rarity => <option value={rarity} key={rarity}>{rarity}성</option>)}</select></label>}
            <label>횟수 계산 방식<select value={effect.count_mode} onChange={event => updateEffect(index, { count_mode: event.target.value as SetEffect["count_mode"] })}><option value="once">조건 충족 시 1회</option><option value="distinct">보유 카드 종류당</option><option value="quantity">보유 카드 1장당</option></select></label>
            <label>YP 증가 대상<select value={effect.bonus_target_scope} onChange={event => { const bonus_target_scope = event.target.value as SetEffect["bonus_target_scope"]; updateEffect(index, { bonus_target_scope, bonus_target_rarity: bonus_target_scope === "rarity" ? effect.bonus_target_rarity ?? 1 : null }); }}><option value="set_members">보유 중인 세트 구성 카드</option><option value="selected_cards">직접 선택한 카드 중 보유 카드</option><option value="rarity">보유 중인 특정 성급 카드</option><option value="collection">보유 중인 모든 카드</option></select></label>
            {effect.bonus_target_scope === "rarity" && <label>YP 증가 대상 성급<select value={effect.bonus_target_rarity ?? 1} onChange={event => updateEffect(index, { bonus_target_rarity: Number(event.target.value) })}>{[1,2,3,4,5].map(rarity => <option value={rarity} key={rarity}>{rarity}성</option>)}</select></label>}
            <label>YP 증가 방식<select value={effect.bonus_type} onChange={event => updateEffect(index, { bonus_type: event.target.value as SetEffect["bonus_type"] })}><option value="fixed">고정 YP 추가</option><option value="percent">최종 YP % 증가</option></select></label>
            <label>증가 수치<input type="number" min="0" step={effect.bonus_type === "fixed" ? 1 : .01} value={effect.value} onChange={event => updateEffect(index, { value: Number(event.target.value) })}/></label>
            <label>최대 적용 횟수<input type="number" min="1" placeholder="제한 없음" value={effect.max_count ?? ""} onChange={event => updateEffect(index, { max_count: event.target.value ? Number(event.target.value) : null })}/></label>
          </div>
          <p className="effect-help">‘보유 카드 종류당’은 세트 완성 전에도 적용됩니다. 다른 방식은 세트 완성 후 적용되며, 계산된 횟수 × 증가 수치가 YP 증가 대상 카드 각각에 반영됩니다.</p>
          {effect.target_scope === "selected_cards" && <div className="target-card-group"><b>적용 횟수를 계산할 카드</b><div className="target-card-list">{cards.map(card => <label key={card.id}><input type="checkbox" checked={effect.target_card_ids.includes(card.id)} onChange={() => toggleTarget(index, card.id, "count")}/>{card.name}</label>)}</div></div>}
          {effect.bonus_target_scope === "selected_cards" && <div className="target-card-group"><b>YP가 증가할 카드</b><div className="target-card-list">{cards.map(card => <label key={card.id}><input type="checkbox" checked={effect.bonus_target_card_ids.includes(card.id)} onChange={() => toggleTarget(index, card.id, "bonus")}/>{card.name}</label>)}</div></div>}
        </div>)}</div>
        <button onClick={() => setDraft({...draft, effects: [...draft.effects, blankEffect()]})}>+ 효과 추가</button>
        <div className="set-save-actions"><button className="primary-button" onClick={save}>세트 저장</button>{draft.id && <button className="danger" onClick={() => remove(draft as CardSet)}>세트 삭제</button>}</div>
      </div>
    </div>
  </section>;
}
