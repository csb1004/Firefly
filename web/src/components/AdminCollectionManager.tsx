import { FormEvent, useState } from "react";
import { api } from "../api";
import type { AdminCollectionState, User } from "../types";
import { Stars } from "./CardTile";

export function AdminCollectionManager() {
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<User[]>([]);
  const [state, setState] = useState<AdminCollectionState>();
  const [drafts, setDrafts] = useState<Record<string, number>>({});
  const [message, setMessage] = useState("");

  async function search(event: FormEvent) {
    event.preventDefault();
    try { setUsers(await api<User[]>(`/api/users/search?q=${encodeURIComponent(query)}`)); }
    catch (error) { setMessage((error as Error).message); }
  }

  async function choose(user: User) {
    try {
      const next = await api<AdminCollectionState>(`/api/admin/users/${user.id}/collection-state`);
      setState(next);
      setDrafts(Object.fromEntries(next.cards.map(card => [card.id, card.quantity])));
    } catch (error) { setMessage((error as Error).message); }
  }

  async function setQuantity(cardId: string) {
    if (!state) return;
    try {
      const next = await api<AdminCollectionState>(`/api/admin/users/${state.user.id}/inventory/${cardId}`, {
        method: "PUT", body: JSON.stringify({ quantity: drafts[cardId] ?? 0 }),
      }, true);
      setState(next);
      setDrafts(Object.fromEntries(next.cards.map(card => [card.id, card.quantity])));
      setMessage("인벤토리 수량을 저장했습니다.");
    } catch (error) { setMessage((error as Error).message); }
  }

  async function setUnlocked(cardId: string, unlocked: boolean) {
    if (!state) return;
    try {
      const next = await api<AdminCollectionState>(`/api/admin/users/${state.user.id}/catalog/${cardId}`, {
        method: "PUT", body: JSON.stringify({ unlocked }),
      }, true);
      setState(next);
      setMessage(unlocked ? "도감을 해금했습니다." : "도감 해금을 취소했습니다.");
    } catch (error) { setMessage((error as Error).message); }
  }

  return <section className="admin-collection-section">
    <div className="section-title"><div><p className="eyebrow">PLAYER DATA</p><h2>인벤토리·도감 관리</h2></div></div>
    {message && <p className="notice">{message}</p>}
    <form className="ticket-search" onSubmit={search}><input value={query} onChange={event => setQuery(event.target.value)} placeholder="사용자명 또는 Discord ID" required/><button>검색</button></form>
    {users.length > 0 && <div className="ticket-search-results">{users.map(user => <button key={user.id} onClick={() => choose(user)}><img src={user.avatar_url} alt=""/><span><b>{user.display_name}</b><small>@{user.username} · {user.discord_id}</small></span></button>)}</div>}
    {state && <div className="panel admin-collection-panel"><div className="admin-player-summary"><strong>{state.user.display_name}</strong><span>{state.total_yp.toLocaleString()} YP</span></div><div className="admin-collection-list">{state.cards.map(card => <div className={`admin-collection-row rarity-${card.rarity}`} key={card.id}><img src={card.image_url} alt=""/><span><b>{card.name}</b><Stars rarity={card.rarity}/><small>예약 {card.reserved_quantity}장</small></span><label>보유량<input type="number" min={card.reserved_quantity} value={drafts[card.id] ?? 0} onChange={event => setDrafts({...drafts, [card.id]: Number(event.target.value)})}/></label><button onClick={() => setQuantity(card.id)}>수량 저장</button><label className="catalog-check"><input type="checkbox" checked={card.unlocked} onChange={event => setUnlocked(card.id, event.target.checked)}/>도감 해금</label></div>)}</div></div>}
  </section>;
}
