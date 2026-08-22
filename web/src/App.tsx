import { FormEvent, useEffect, useState } from "react";
import { api, idempotencyKey, openRealtime } from "./api";
import { CardTile, Stars } from "./components/CardTile";
import { ImageCropper } from "./components/ImageCropper";
import { Reveal } from "./components/Reveal";
import { AdminCollectionManager } from "./components/AdminCollectionManager";
import { AdminSetManager } from "./components/AdminSetManager";
import type { Card, Catalog, Collection, DrawStatus, TradeRoom, User } from "./types";

type FeedItem = { id: string; drawn_at: string; user_id: number; username: string; display_name: string; card_id: string; card_name: string };

function navigate(path: string) {
  history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function Login() {
  return <main className="boot-shell"><div className="brand-mark">✦</div><p className="eyebrow">YOUNGHO GACHA</p><h1>영호 가챠</h1><p>매일 새로운 기회, Discord 계정에 이어지는 나만의 컬렉션</p><a className="primary-button" href="/api/auth/discord">Discord로 시작하기</a></main>;
}

function Warning({ onDone }: { onDone: () => void }) {
  const [error, setError] = useState("");
  async function accept() {
    try { await api("/api/me/warning", { method: "POST" }, true); onDone(); }
    catch (e) { setError((e as Error).message); }
  }
  return <main className="center-panel"><div className="brand-mark">!</div><h1 className="welcome-title">시작하기 전에</h1><p>반디와 공유하는 서버가 없거나 Discord DM을 막아두면 선물·거래 알림을 받지 못할 수 있어요. 사이트 기능과 획득한 카드는 그대로 유지됩니다.</p>{error && <p className="error">{error}</p>}<button className="primary-button" onClick={accept}>확인하고 시작</button></main>;
}

function Shell({ me, children, feed, invite }: { me: User; children: React.ReactNode; feed: FeedItem[]; invite?: TradeRoom }) {
  return <div className="app-shell">
    <header><button className="logo" onClick={() => navigate("/")}><span>✦</span> 영호 가챠</button><nav>
      <button onClick={() => navigate("/")}>뽑기</button><button onClick={() => navigate("/collection")}>컬렉션</button><button onClick={() => navigate("/catalog")}>도감</button><button onClick={() => navigate("/ranking")}>랭킹</button><button onClick={() => navigate("/search")}>검색</button><button onClick={() => navigate("/settings")}>설정</button>{me.is_admin && <button onClick={() => navigate("/admin")}>관리</button>}
    </nav><button className="avatar-button" onClick={() => navigate(`/profile/${me.id}`)}><img src={me.avatar_url} alt="" />{me.display_name}</button></header>
    {invite && invite.status === "invited" && invite.invitee_id === me.id && <div className="invite-banner"><span>새 거래 초대가 도착했습니다.</span><button onClick={() => navigate(`/trade/${invite.id}`)}>확인</button></div>}
    <main className="content">{children}</main>
    <footer><div className="footer-title"><strong>최근 5성</strong><button onClick={()=>navigate("/five-stars")}>전체 기록</button></div><div className="feed-strip">{feed.length ? feed.map(item => <div className="feed-item" key={item.id}><time>{new Date(item.drawn_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</time><button onClick={() => navigate(`/profile/${item.user_id}`)}>{item.display_name}</button><button onClick={() => navigate(`/card/${item.card_id}`)}>{item.card_name}</button></div>) : <span>아직 5성 기록이 없습니다.</span>}</div></footer>
  </div>;
}

function DrawPage() {
  const [status, setStatus] = useState<DrawStatus>();
  const [probability, setProbability] = useState<any>();
  const [reveal, setReveal] = useState<Card>();
  const [results, setResults] = useState<Card[]>([]);
  const [error, setError] = useState("");
  const load = () => Promise.all([api<any>("/api/draw/status"), api<any>("/api/probabilities/current")]).then(([s, p]) => { setStatus(s); setProbability(p); });
  useEffect(() => { load().catch(e => setError(e.message)); }, []);
  async function draw(count: 1 | 10) {
    setError("");
    try {
      const data = await api<any>(count === 10 ? "/api/draw/ten" : "/api/draw", { method: "POST", body: JSON.stringify({ idempotency_key: idempotencyKey(count === 10 ? "draw-ten" : "draw") }) }, true);
      const cards: Card[] = count === 10 ? data.cards : [data.card];
      setResults(cards);
      setReveal(cards.reduce((highest, card) => card.rarity > highest.rarity ? card : highest));
      await load();
    }
    catch (e) { setError((e as Error).message); }
  }
  return <><section className="hero-panel"><p className="eyebrow">DAILY SIGNAL</p><h1>오늘의 카드</h1><p>일일 뽑기는 오전 5시에 다시 채워집니다.</p><div className="ticket-balance"><span>오늘 남은 횟수 <b>{status?.daily_remaining ?? "–"}</b></span><span>추가 뽑기권 <b>{status?.bonus_tickets ?? "–"}</b></span></div><div className="pity-grid"><div><span>4성 이상 확정까지</span><b>{status?.four_remaining ?? "–"}회</b></div><div><span>5성 확정까지</span><b>{status?.five_remaining ?? "–"}회</b></div></div><div className="draw-actions"><button className="draw-button" disabled={!status?.eligible} onClick={() => draw(1)}>{status?.eligible ? `1회 뽑기 · ${status.draws_remaining}회 남음` : "사용 가능한 뽑기권 없음"}</button><button className="draw-button ten" disabled={(status?.draws_remaining ?? 0) < 10} onClick={() => draw(10)}>10회 뽑기</button></div>{error && <p className="error">{error}</p>}</section>
    <section className="panel"><div className="section-title"><div><p className="eyebrow">LIVE ODDS</p><h2>현재 확률</h2></div></div><div className="odds-row">{probability && Object.entries(probability.rarities).map(([rarity, chance]) => <div className={`odds rarity-${rarity}`} key={rarity}><Stars rarity={Number(rarity)} /><b>{Number(chance).toFixed(4)}%</b></div>)}</div><details><summary>카드별 상세 확률</summary><div className="probability-list">{probability?.cards.map((item: any) => <span key={item.card_id}>{item.name}<b>{item.probability.toFixed(6)}%</b></span>)}</div></details></section>
    {results.length > 0 && <section className="draw-results"><div className="section-title"><div><p className="eyebrow">RESULT</p><h2>{results.length}회 뽑기 결과</h2></div></div><div className="card-grid">{results.map((card, index) => <CardTile card={card} key={`${card.id}-${index}`} onClick={() => navigate(`/card/${card.id}`)}/>)}</div></section>}
    {reveal && <Reveal card={reveal} onClose={() => setReveal(undefined)} />}</>;
}

function CollectionPage({ userId }: { userId?: number }) {
  const [data, setData] = useState<Collection>();
  const [error, setError] = useState("");
  const load = () => api<Collection>(userId ? `/api/users/${userId}/collection` : "/api/collection/me").then(setData).catch(e => setError(e.message));
  useEffect(() => { load(); }, [userId]);
  async function discard(card: Card) {
    const quantity = Number(prompt(`${card.name} 버릴 수량 (거래 예약분 제외 최대 ${card.available_quantity})`, "1"));
    if (!Number.isInteger(quantity) || quantity < 1) return;
    try {
      const preview = await api<any>("/api/collection/discard/preview", { method: "POST", body: JSON.stringify({ card_id: card.id, quantity }) });
      if (!confirm(`${preview.card_name} ${quantity}장을 버릴까요?\n보유 ${preview.quantity_after}장 · YP ${preview.yp_before.toLocaleString()} → ${preview.yp_after.toLocaleString()} (${preview.yp_change >= 0 ? "+" : ""}${preview.yp_change})\n도감 해금 기록은 유지됩니다.`)) return;
      await api("/api/collection/discard", { method: "POST", body: JSON.stringify({ card_id: card.id, quantity, idempotency_key: idempotencyKey("discard") }) }, true);
      await load();
    } catch (e) { setError((e as Error).message); }
  }
  return <section><div className="section-title"><div><p className="eyebrow">ARCHIVE</p><h1>컬렉션</h1></div><strong className="yp-total">{data?.total_yp.toLocaleString() ?? 0} YP</strong></div>{data?.base_yp !== undefined && <div className="yp-breakdown"><span>기본 {data.base_yp.toLocaleString()}</span><span>고정 +{data.fixed_bonus?.toLocaleString()}</span><span>최종 +{data.percent_bonus}%</span>{data.active_sets?.map(name => <b key={name}>✦ {name}</b>)}</div>}{error && <p className="error">{error}</p>}<div className="card-grid">{data?.cards.map(card => <div className="collection-card" key={card.id}><CardTile card={card} onClick={() => navigate(`/card/${card.id}`)}/>{!userId && <button className="discard-button" onClick={() => discard(card)} disabled={(card.available_quantity ?? 0) < 1}>카드 버리기</button>}</div>)}</div>{data?.cards.length === 0 && <div className="empty">아직 보유한 카드가 없습니다. 도감 해금 기록은 유지됩니다.</div>}</section>;
}

function CatalogPage() {
  const [catalog, setCatalog] = useState<Catalog>();
  const [rarity, setRarity] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => { api<Catalog>("/api/catalog").then(setCatalog).catch(e => setError(e.message)); }, []);
  const cards = catalog?.cards.filter(card => !rarity || card.rarity === rarity) ?? [];
  const percent = catalog?.total_count ? Math.round(catalog.owned_count / catalog.total_count * 100) : 0;
  return <section><div className="catalog-head"><div><p className="eyebrow">CARD INDEX</p><h1>도감</h1><p>획득한 카드와 아직 만나지 못한 카드를 한눈에 확인하세요.</p></div><div className="catalog-progress"><strong>{catalog?.owned_count ?? 0}<small> / {catalog?.total_count ?? 0}</small></strong><span>수집률 {percent}%</span><i style={{width:`${percent}%`}} /></div></div><div className="rarity-filters"><button className={rarity===0?"active":""} onClick={()=>setRarity(0)}>전체</button>{[1,2,3,4,5].map(value=><button className={`${rarity===value?"active":""} rarity-${value}`} onClick={()=>setRarity(value)} key={value}><Stars rarity={value}/></button>)}</div>{error&&<p className="error">{error}</p>}<div className="catalog-grid">{cards.map(card=><div className={`catalog-entry ${card.owned?"owned":"locked"}`} key={card.id}><CardTile card={card.owned?card:{...card,quantity:undefined}} onClick={()=>navigate(`/card/${card.id}`)}/><span className="catalog-state">{card.owned?`보유 ×${card.quantity}`:"미획득"}</span></div>)}</div>{catalog && cards.length===0&&<div className="empty">이 등급에는 카드가 없습니다.</div>}</section>;
}

function RankingPage() {
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { api<any>("/api/rankings").then(data => setItems(data.items)); }, []);
  return <section><div className="section-title"><div><p className="eyebrow">GLOBAL RANK</p><h1>YP 랭킹</h1></div></div><div className="ranking-list">{items.map(item => <button key={item.user_id} onClick={() => navigate(`/profile/${item.user_id}`)}><span className="rank">#{item.rank}</span><img src={item.avatar_url} alt="" /><span><b>{item.display_name}</b><small>@{item.username}</small></span><strong>{item.total_yp.toLocaleString()} YP</strong></button>)}</div></section>;
}

function FiveStarHistoryPage() {
  const [page,setPage]=useState(1);const [items,setItems]=useState<FeedItem[]>([]);
  useEffect(()=>{api<any>(`/api/feed/five-stars?page=${page}`).then(data=>setItems(data.items));},[page]);
  return <section><div className="section-title"><div><p className="eyebrow">GOLDEN ARCHIVE</p><h1>5성 획득 기록</h1></div></div><div className="history-list">{items.map(item=><div key={item.id}><time>{new Date(item.drawn_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})}</time><button onClick={()=>navigate(`/profile/${item.user_id}`)}>{item.display_name} <small>@{item.username}</small></button><button className="gold" onClick={()=>navigate(`/card/${item.card_id}`)}>{item.card_name}</button></div>)}</div><div className="pager"><button disabled={page===1} onClick={()=>setPage(page-1)}>이전</button><span>{page} 페이지</span><button disabled={items.length<20} onClick={()=>setPage(page+1)}>다음</button></div></section>;
}

function CardDetailPage({cardId}:{cardId:string}) { const [card,setCard]=useState<Card>();useEffect(()=>{api<Card>(`/api/cards/${cardId}`).then(setCard);},[cardId]);return <section className="card-detail">{card?<><CardTile card={card}/><div><p className="eyebrow">CARD DETAIL</p><h1>{card.name}</h1><Stars rarity={card.rarity}/><strong>{card.yp.toLocaleString()} YP</strong></div></>:<div className="empty">카드를 불러오는 중…</div>}</section>; }

function SearchPage() {
  const [q, setQ] = useState(""); const [items, setItems] = useState<User[]>([]); const [error, setError] = useState("");
  async function submit(e: FormEvent) { e.preventDefault(); try { setItems(await api<User[]>(`/api/users/search?q=${encodeURIComponent(q)}`)); } catch (e) { setError((e as Error).message); } }
  return <section><div className="section-title"><div><p className="eyebrow">DISCOVERY</p><h1>사용자 검색</h1></div></div><form className="search-form" onSubmit={submit}><input value={q} onChange={e => setQ(e.target.value)} placeholder="사용자명, 표시 이름 또는 Discord ID" /><button>검색</button></form>{error && <p className="error">{error}</p>}<div className="people-grid">{items.map(user => <button key={user.id} onClick={() => navigate(`/profile/${user.id}`)}><img src={user.avatar_url} alt="" /><span><b>{user.display_name}</b><small>@{user.username} · {user.discord_id}</small></span></button>)}</div></section>;
}

function ProfilePage({ me, userId }: { me: User; userId: number }) {
  const [user, setUser] = useState<User>(); const [collection, setCollection] = useState<Collection>(); const [mine, setMine] = useState<Collection>(); const [online, setOnline] = useState(false); const [giftCard, setGiftCard] = useState(""); const [quantity, setQuantity] = useState(1); const [message, setMessage] = useState("");
  useEffect(() => { Promise.all([api<User>(`/api/users/${userId}`), api<Collection>(`/api/users/${userId}/collection`), api<any>(`/api/presence/${userId}`), api<Collection>("/api/collection/me")]).then(([u, c, p, own]) => { setUser(u); setCollection(c); setMine(own); setOnline(p.online); if (own.cards[0]) setGiftCard(own.cards[0].id); }); }, [userId]);
  async function gift() { try { const preview = await api<any>("/api/gifts/preview", { method: "POST", body: JSON.stringify({ receiver_id: userId, card_id: giftCard, quantity }) }); if (!confirm(`${preview.card.name} ×${quantity}\n내 YP ${preview.sender_yp_change}\n상대 YP +${preview.receiver_yp_change}\n선물할까요?`)) return; await api("/api/gifts", { method: "POST", body: JSON.stringify({ receiver_id: userId, card_id: giftCard, quantity, idempotency_key: idempotencyKey("gift") }) }, true); setMessage("선물이 즉시 전달되었습니다."); } catch (e) { setMessage((e as Error).message); } }
  async function trade() { try { const room = await api<TradeRoom>("/api/trades/invite", { method: "POST", body: JSON.stringify({ invitee_id: userId }) }, true); navigate(`/trade/${room.id}`); } catch (e) { setMessage((e as Error).message); } }
  if (!user) return <div className="empty">프로필을 불러오는 중…</div>;
  return <section><div className="profile-head"><img src={user.avatar_url} alt="" /><div><p className="eyebrow">DISCORD PROFILE</p><h1>{user.display_name}</h1><p>@{user.username} · {user.discord_id}</p></div><strong>{collection?.total_yp.toLocaleString()} YP</strong></div>{me.id !== userId && <div className="action-panel"><select value={giftCard} onChange={e => setGiftCard(e.target.value)}>{mine?.cards.map(card => <option value={card.id} key={card.id}>{card.name} (보유 {card.available_quantity})</option>)}</select><input type="number" min="1" value={quantity} onChange={e => setQuantity(Number(e.target.value))} /><button onClick={gift} disabled={!user.accepts_gifts}>즉시 선물</button><button onClick={trade} disabled={!online || !user.accepts_trades}>{online ? "실시간 거래" : "오프라인"}</button></div>}{message && <p className="notice">{message}</p>}<CollectionPage userId={userId} /></section>;
}

function SettingsPage({ me, refresh }: { me: User; refresh: () => void }) {
  const [gifts, setGifts] = useState(me.accepts_gifts); const [trades, setTrades] = useState(me.accepts_trades); const [message, setMessage] = useState("");
  async function save() { try { await api("/api/me/settings", { method: "PUT", body: JSON.stringify({ accepts_gifts: gifts, accepts_trades: trades }) }, true); setMessage("저장했습니다."); refresh(); } catch (e) { setMessage((e as Error).message); } }
  return <section className="narrow"><p className="eyebrow">PREFERENCES</p><h1>수신 설정</h1><label className="toggle"><span><b>선물 받기</b><small>오프라인이어도 즉시 들어옵니다.</small></span><input type="checkbox" checked={gifts} onChange={e => setGifts(e.target.checked)} /></label><label className="toggle"><span><b>거래 초대 받기</b><small>온라인일 때만 초대받습니다.</small></span><input type="checkbox" checked={trades} onChange={e => setTrades(e.target.checked)} /></label><button className="primary-button" onClick={save}>설정 저장</button>{message && <p className="notice">{message}</p>}</section>;
}

function TradePage({ me, roomId }: { me: User; roomId: string }) {
  const [room, setRoom] = useState<TradeRoom>(); const [mine, setMine] = useState<Collection>(); const [theirs, setTheirs] = useState<Collection>(); const [requestCard, setRequestCard] = useState(""); const [message, setMessage] = useState("");
  const load = async () => { const r=await api<TradeRoom>(`/api/trades/${roomId}`); const other=r.inviter_id===me.id?r.invitee_id:r.inviter_id; const [own,otherCollection]=await Promise.all([api<Collection>("/api/collection/me"),api<Collection>(`/api/users/${other}/collection`)]); setRoom(r);setMine(own);setTheirs(otherCollection);if(otherCollection.cards[0])setRequestCard(otherCollection.cards[0].id); };
  useEffect(() => { load().catch(e => setMessage(e.message)); const handler=(event:Event)=>{const updated=(event as CustomEvent<TradeRoom>).detail;if(updated.id===roomId)setRoom(updated);};addEventListener("trade-room-update",handler);return()=>removeEventListener("trade-room-update",handler); }, [roomId]);
  async function action(path: string, body?: any, method="POST") { try { const result = await api<TradeRoom>(`/api/trades/${roomId}/${path}`, { method, body: body ? JSON.stringify(body) : undefined }, true); setRoom(result); } catch (e) { setMessage((e as Error).message); } }
  if (!room) return <div className="empty">거래방을 불러오는 중…</div>;
  const other = room.inviter_id === me.id ? room.invitee_id : room.inviter_id;
  return <section><div className="section-title"><div><p className="eyebrow">LIVE EXCHANGE</p><h1>실시간 거래</h1></div><span className={`status ${room.status}`}>{room.status}</span></div>{room.status === "invited" && room.invitee_id === me.id && <button className="primary-button" onClick={() => action("accept-invite")}>초대 수락</button>}<div className="trade-columns">{[me.id, other].map(userId => <div className="trade-offer" key={userId}><h2>{userId === me.id ? "내 제안" : "상대 제안"} {room.accepted[String(userId)] && <span>✓ 수락</span>}</h2>{room.yp_preview?.[String(userId)] && <p className="trade-yp">YP {room.yp_preview[String(userId)].before.toLocaleString()} → <b>{room.yp_preview[String(userId)].after.toLocaleString()}</b> ({room.yp_preview[String(userId)].change >= 0 ? "+" : ""}{room.yp_preview[String(userId)].change.toLocaleString()})</p>}{room.offers.filter(o => o.user_id === userId).map(o => <div className={`offer-row rarity-${o.rarity}`} key={o.card_id}>{o.card_name}<b>×{o.quantity}</b></div>)}</div>)}</div>{room.status === "negotiating" && <><h2>내 카드 추가</h2><div className="inventory-strip">{mine?.cards.map(card => <button key={card.id} onClick={() => { const quantity = Number(prompt(`${card.name} 제안 수량`, "1")); if (quantity >= 0) action("offer", { card_id: card.id, quantity }, "PUT"); }}><img src={card.image_url} alt="" /><span>{card.name}<small>가능 {card.available_quantity}</small></span></button>)}</div><div className="specific-request"><select value={requestCard} onChange={e=>setRequestCard(e.target.value)}>{theirs?.cards.map(card=><option key={card.id} value={card.id}>{card.name} (보유 {card.quantity})</option>)}</select><button onClick={()=>{const quantity=Number(prompt("요청 수량","1"));if(quantity>0)action("request",{card_id:requestCard,quantity,message:"이 카드를 제안해주세요."});}}>특정 카드 요구</button></div><div className="trade-actions"><button onClick={() => action("request", { message: "카드를 조금 더 제안해주세요." })}>더 요구하기</button><button className="accept" onClick={() => action("accept")}>이 제안 수락</button><button className="danger" onClick={() => action("cancel")}>거절·나가기</button></div></>}{room.requests.map(request => <p className="request" key={request.id}>요청: {request.message || `${request.quantity}장 더 요청`}</p>)}{message && <p className="error">{message}</p>}</section>;
}

type TicketView = {
  user: User;
  draws_remaining: number;
  daily_remaining: number;
  bonus_tickets: number;
  restored?: number;
};

function DrawTicketAdmin() {
  const [dailyDraws, setDailyDraws] = useState(1);
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<User[]>([]);
  const [selected, setSelected] = useState<TicketView>();
  const [grantAmount, setGrantAmount] = useState(1);
  const [message, setMessage] = useState("");
  useEffect(() => { api<{daily_draws:number}>("/api/admin/draw-settings").then(data=>setDailyDraws(data.daily_draws)).catch(e=>setMessage(e.message)); }, []);
  async function saveDaily() { try { const data=await api<{daily_draws:number}>("/api/admin/draw-settings",{method:"PUT",body:JSON.stringify({daily_draws:dailyDraws})},true);setDailyDraws(data.daily_draws);setMessage(`매일 ${data.daily_draws}회 지급으로 변경했습니다.`); } catch(e){setMessage((e as Error).message);} }
  async function search(e: FormEvent) { e.preventDefault(); try { setUsers(await api<User[]>(`/api/users/search?q=${encodeURIComponent(query)}`)); } catch(e){setMessage((e as Error).message);} }
  async function selectUser(user: User) { try { setSelected(await api<TicketView>(`/api/admin/users/${user.id}/draw-tickets`)); } catch(e){setMessage((e as Error).message);} }
  async function grant() { if(!selected)return;try{const next=await api<TicketView>(`/api/admin/users/${selected.user.id}/draw-tickets/grant`,{method:"POST",body:JSON.stringify({amount:grantAmount})},true);setSelected(next);setMessage(`${next.user.display_name}님에게 추가 뽑기권 ${grantAmount}장을 지급했습니다.`);}catch(e){setMessage((e as Error).message);} }
  async function resetToday() { if(!selected||!confirm(`${selected.user.display_name}님의 오늘 사용 횟수를 복구할까요?\n천장 횟수와 획득 카드는 유지됩니다.`))return;try{const next=await api<TicketView>(`/api/admin/users/${selected.user.id}/draw-tickets/reset-today`,{method:"POST"},true);setSelected(next);setMessage(`${next.user.display_name}님의 오늘 사용분 ${next.restored ?? 0}회를 복구했습니다.`);}catch(e){setMessage((e as Error).message);} }
  return <section className="admin-ticket-section"><div className="section-title"><div><p className="eyebrow">DRAW CONTROL</p><h2>뽑기권 관리</h2></div></div>{message&&<p className="notice">{message}</p>}<div className="admin-ticket-grid"><div className="panel ticket-settings"><h3>매일 기본 지급</h3><p>모든 플레이어에게 오전 5시 기준으로 적용됩니다.</p><label><input type="number" min="0" max="100" value={dailyDraws} onChange={e=>setDailyDraws(Number(e.target.value))}/><span>회</span></label><button onClick={saveDaily}>지급량 저장</button></div><div className="panel player-ticket-panel"><h3>플레이어별 관리</h3><form className="ticket-search" onSubmit={search}><input value={query} onChange={e=>setQuery(e.target.value)} placeholder="사용자명 또는 Discord ID" required/><button>검색</button></form>{users.length>0&&<div className="ticket-search-results">{users.map(user=><button key={user.id} onClick={()=>selectUser(user)}><img src={user.avatar_url} alt=""/><span><b>{user.display_name}</b><small>@{user.username} · {user.discord_id}</small></span></button>)}</div>}{selected&&<div className="selected-ticket-user"><div className="ticket-user-head"><img src={selected.user.avatar_url} alt=""/><span><b>{selected.user.display_name}</b><small>@{selected.user.username}</small></span></div><div className="ticket-stats"><span>총 사용 가능<b>{selected.draws_remaining}회</b></span><span>오늘 기본분<b>{selected.daily_remaining}회</b></span><span>추가권<b>{selected.bonus_tickets}장</b></span></div><div className="ticket-actions"><label><input type="number" min="1" max="10000" value={grantAmount} onChange={e=>setGrantAmount(Number(e.target.value))}/><span>장</span></label><button onClick={grant}>추가권 지급</button><button className="danger" onClick={resetToday}>오늘 사용량 초기화</button></div></div>}</div></div></section>;
}

function AdminPage() {
  const [cards, setCards] = useState<Card[]>([]);
  const [prob, setProb] = useState<Record<string, number>>({ "1":45,"2":30,"3":19.3,"4":5.1,"5":0.6 });
  const [message, setMessage] = useState("");
  const [newImage, setNewImage] = useState<File>();
  const [cropTarget, setCropTarget] = useState<{ file: File; card?: Card }>();
  const load = () => Promise.all([api<Card[]>("/api/admin/cards"), api<any>("/api/probabilities")]).then(([c,p]) => { setCards(c); setProb(p.rarities); });
  useEffect(() => { load().catch(e => setMessage(e.message)); }, []);
  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newImage) { setMessage("카드 이미지를 선택하고 3:4 영역을 맞춰주세요."); return; }
    const element = e.currentTarget;
    const form = new FormData(element);
    form.set("image", newImage);
    try {
      await api("/api/admin/cards", { method: "POST", body: form }, true);
      element.reset();
      setNewImage(undefined);
      setMessage("카드를 추가했습니다. 상세 확률에도 바로 반영됩니다.");
      await load();
    } catch (error) { setMessage((error as Error).message); }
  }
  async function toggle(card: Card) { const form = new FormData(); form.set("name", card.name); form.set("rarity", String(card.rarity)); form.set("yp", String(card.yp)); if(card.weight) form.set("weight", String(card.weight)); form.set("active", String(!card.active)); try { await api(`/api/admin/cards/${card.id}`, { method:"PUT", body:form }, true); await load(); } catch(e) { setMessage((e as Error).message); } }
  async function edit(card: Card) { const name=prompt("카드 이름",card.name);if(!name)return;const rarity=Number(prompt("등급 (1~5)",String(card.rarity)));const yp=Number(prompt("YP",String(card.yp)));const weightText=prompt("가중치 (비우면 동일 가중치)",card.weight?String(card.weight):"");const form=new FormData();form.set("name",name);form.set("rarity",String(rarity));form.set("yp",String(yp));if(weightText)form.set("weight",weightText);form.set("active",String(card.active));try{await api(`/api/admin/cards/${card.id}`,{method:"PUT",body:form},true);await load();}catch(e){setMessage((e as Error).message);} }
  async function replaceImage(card: Card,file:File) { const form=new FormData();form.set("name",card.name);form.set("rarity",String(card.rarity));form.set("yp",String(card.yp));if(card.weight)form.set("weight",String(card.weight));form.set("active",String(card.active));form.set("image",file);try{await api(`/api/admin/cards/${card.id}`,{method:"PUT",body:form},true);setMessage(`${card.name} 이미지를 교체했습니다.`);await load();}catch(e){setMessage((e as Error).message);} }
  async function remove(card: Card) { try { const preview = await api<any>(`/api/admin/cards/${card.id}/delete-preview`); const typed = prompt(`영구 삭제: ${preview.affected_players}명, ${preview.total_copies}장, 거래방 ${preview.active_trade_rooms}개 영향\n카드 이름을 입력하세요.`); if (!typed) return; await api(`/api/admin/cards/${card.id}`, { method:"DELETE", body:JSON.stringify({ confirm_name:typed }) }, true); await load(); } catch(e) { setMessage((e as Error).message); } }
  async function saveProb() { try { await api("/api/admin/probabilities", { method:"PUT", body:JSON.stringify({ probabilities:prob }) }, true); setMessage("확률을 저장했습니다."); } catch(e) { setMessage((e as Error).message); } }
  function finishCrop(file: File) {
    const target = cropTarget;
    setCropTarget(undefined);
    if (target?.card) void replaceImage(target.card, file);
    else setNewImage(file);
  }
  return <>
    <section><p className="eyebrow">SPECIAL USER CONTROL</p><h1>관리자 센터</h1><DrawTicketAdmin/><AdminCollectionManager/><AdminSetManager cards={cards}/><div className="section-title admin-card-heading"><div><p className="eyebrow">CARD CONTROL</p><h2>카드 관리</h2></div></div>{message && <p className="notice">{message}</p>}<div className="admin-grid"><form className="panel form-grid" onSubmit={create}><h2>새 카드</h2><label>이름<input name="name" required maxLength={100}/></label><label>등급<select name="rarity">{[1,2,3,4,5].map(v=><option key={v} value={v}>{v}성</option>)}</select></label><label>YP<input name="yp" type="number" min="0" required/></label><label>가중치<input name="weight" type="number" min="0.000001" step="any"/></label><label>이미지<input type="file" accept="image/png,image/jpeg,image/webp" onChange={event => { const file=event.target.files?.[0]; if(file)setCropTarget({file}); event.target.value=""; }}/><small className={newImage ? "image-ready" : ""}>{newImage ? `✓ 3:4 자르기 완료 · ${newImage.name}` : "선택 후 확대·이동하여 3:4로 자릅니다."}</small></label><input type="hidden" name="active" value="true"/><button className="primary-button">카드 추가</button></form><div className="panel"><h2>등급 확률</h2>{[1,2,3,4,5].map(r => <label className="prob-input" key={r}><Stars rarity={r}/><input type="number" step="0.0001" value={prob[String(r)] ?? 0} onChange={e => setProb({...prob,[String(r)]:Number(e.target.value)})}/><span>%</span></label>)}<button onClick={saveProb}>확률 저장</button></div></div><div className="admin-card-list">{cards.map(card => <div key={card.id}><CardTile card={card} compact/><div><button onClick={()=>edit(card)}>정보·등급 수정</button><button onClick={()=>toggle(card)}>{card.active ? "뽑기 제외" : "다시 활성화"}</button></div><div><label className="file-button">이미지 교체<input type="file" hidden accept="image/png,image/jpeg,image/webp" onChange={event=>{const file=event.target.files?.[0];if(file)setCropTarget({file,card});event.target.value="";}}/></label><button className="danger" onClick={()=>remove(card)}>영구 삭제</button></div></div>)}</div></section>
    {cropTarget && <ImageCropper file={cropTarget.file} onCancel={()=>setCropTarget(undefined)} onConfirm={finishCrop}/>}
  </>;
}

export default function App() {
  const [me, setMe] = useState<User | null | undefined>(); const [path, setPath] = useState(location.pathname); const [feed, setFeed] = useState<FeedItem[]>([]); const [invite, setInvite] = useState<TradeRoom>();
  const refresh = () => api<User>("/api/auth/me").then(setMe).catch(() => setMe(null));
  useEffect(() => { const handler=()=>setPath(location.pathname); addEventListener("popstate",handler); refresh(); return()=>removeEventListener("popstate",handler); }, []);
  useEffect(() => {
    if (!me?.warning_acknowledged) return;
    api<any>("/api/feed/five-stars").then(data => setFeed(data.items)).catch(() => {});
    let socket: WebSocket | undefined;
    let retryTimer: number | undefined;
    let stopped = false;
    let retryDelay = 500;
    const onMessage = (message: any) => {
      if (message.type === "trade.invited") setInvite(message.room);
      if (message.room?.id) window.dispatchEvent(new CustomEvent("trade-room-update", { detail: message.room }));
    };
    const connect = async () => {
      try {
        const next = await openRealtime(onMessage);
        if (stopped) { next.close(); return; }
        socket = next;
        next.addEventListener("open", () => { retryDelay = 500; });
        next.addEventListener("close", () => {
          if (stopped) return;
          retryTimer = window.setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 5000);
        });
      } catch {
        if (!stopped) {
          retryTimer = window.setTimeout(connect, retryDelay);
          retryDelay = Math.min(retryDelay * 2, 5000);
        }
      }
    };
    connect();
    return () => {
      stopped = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [me?.id, me?.warning_acknowledged]);
  if (me === undefined) return <div className="boot-shell"><div className="brand-mark pulse">✦</div></div>;
  if (me === null) return <Login/>;
  if (!me.warning_acknowledged) return <Warning onDone={refresh}/>;
  let page: React.ReactNode = <DrawPage/>;
  if(path==="/collection") page=<CollectionPage/>; else if(path==="/catalog") page=<CatalogPage/>; else if(path==="/ranking") page=<RankingPage/>; else if(path==="/search") page=<SearchPage/>; else if(path==="/settings") page=<SettingsPage me={me} refresh={refresh}/>; else if(path==="/five-stars") page=<FiveStarHistoryPage/>; else if(path==="/admin" && me.is_admin) page=<AdminPage/>; else if(path.startsWith("/profile/")) page=<ProfilePage me={me} userId={Number(path.split("/").pop())}/>; else if(path.startsWith("/trade/")) page=<TradePage me={me} roomId={path.split("/").pop()!}/>; else if(path.startsWith("/card/")) page=<CardDetailPage cardId={path.split("/").pop()!}/>;
  return <Shell me={me} feed={feed} invite={invite}>{page}</Shell>;
}
