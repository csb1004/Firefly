import type { Card } from "../types";
import { CardTile } from "./CardTile";

export function sortCardsByRarity(cards: Card[]) {
  return cards
    .map((card, drawOrder) => ({ card, drawOrder }))
    .sort((left, right) => right.card.rarity - left.card.rarity || left.drawOrder - right.drawOrder)
    .map(item => item.card);
}

export function Reveal({ cards, onClose }: { cards: Card[]; onClose: () => void }) {
  const highestRarity = Math.max(...cards.map(card => card.rarity));
  const isBatch = cards.length > 1;
  const displayCards = isBatch ? sortCardsByRarity(cards) : cards;
  return (
    <div className={`reveal-overlay reveal-${highestRarity} ${isBatch ? "batch" : ""}`} role="dialog" aria-label={`${cards.length}장 카드 획득`}>
      <button className="skip" onClick={onClose}>건너뛰기</button>
      <div className="warp-lines" aria-hidden="true" />
      {isBatch ? <div className="reveal-batch"><p className="obtained">10 DRAW RESULT · {highestRarity} STAR MAX</p><div className="reveal-batch-grid">{displayCards.map((card, index) => <div className="reveal-batch-card" key={`${card.id}-${index}`}><CardTile card={card} compact/></div>)}</div></div> : <><div className="reveal-card"><CardTile card={cards[0]} /></div><p className="obtained">NEW DRAW · {cards[0].rarity} STAR</p></>}
      <button className="primary-button" onClick={onClose}>확인</button>
    </div>
  );
}
