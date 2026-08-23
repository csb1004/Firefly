import { useEffect, useState } from "react";
import { api } from "../api";
import type { DrawHistoryResponse } from "../types";
import { Stars } from "./CardTile";

export function DrawHistoryPage({ onCard }: { onCard: (cardId: string) => void }) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<DrawHistoryResponse>();
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    api<DrawHistoryResponse>(`/api/draw/history?page=${page}&page_size=50`).then(setData).catch(next => setError(next.message));
  }, [page]);

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / 50));
  return <section className="draw-history-page">
    <div className="draw-history-head"><div><p className="eyebrow">WARP TRACKER</p><h1>나의 뽑기 기록</h1><p>첫 뽑기부터 지금까지, 어떤 순서로 카드를 획득했는지 확인하세요.</p></div></div>
    <div className="draw-history-summary"><span>누적 뽑기<strong>{data?.summary.total_draws.toLocaleString() ?? "–"}회</strong></span><span>4성 이상 확정까지<strong>{data?.summary.four_remaining ?? "–"}회</strong></span><span>5성 확정까지<strong>{data?.summary.five_remaining ?? "–"}회</strong></span></div>
    {error&&<p className="error">{error}</p>}
    <div className="draw-history-list">{data?.items.map(item => <article className={`draw-history-row rarity-${item.card_rarity}`} key={item.id}>
      <strong className="draw-history-number">#{item.draw_number}</strong>
      <div className="draw-history-art">{item.image_url?<img src={item.image_url} alt=""/>:<span>이미지 없음</span>}</div>
      <div className="draw-history-card"><button disabled={!item.card_id} aria-label={`${item.card_name} 상세 보기`} onClick={()=>item.card_id&&onCard(item.card_id)}>{item.card_name}</button><Stars rarity={item.card_rarity}/><small>{item.card_yp.toLocaleString()} YP</small></div>
      <div className="draw-history-source"><b>{item.batch_id ? `10회 뽑기 · ${(item.batch_position ?? 0) + 1}번째` : "1회 뽑기"}</b><small>{item.ticket_source === "daily" ? "매일 기본 지급" : "추가 뽑기권"}</small></div>
      <time>{new Date(item.drawn_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" })}</time>
    </article>)}</div>
    {data&&data.items.length===0&&<div className="empty">아직 뽑기 기록이 없습니다.</div>}
    <div className="pager"><button aria-label="이전" disabled={page===1} onClick={()=>setPage(page-1)}>이전</button><span>{page} / {totalPages}</span><button aria-label="다음" disabled={page>=totalPages} onClick={()=>setPage(page+1)}>다음</button></div>
  </section>;
}
