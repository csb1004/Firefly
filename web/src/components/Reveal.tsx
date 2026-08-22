import type { Card } from "../types";
import { CardTile } from "./CardTile";

export function Reveal({ card, onClose }: { card: Card; onClose: () => void }) {
  return (
    <div className={`reveal-overlay reveal-${card.rarity}`} role="dialog" aria-label={`${card.rarity}성 카드 획득`}>
      <button className="skip" onClick={onClose}>건너뛰기</button>
      <div className="warp-lines" aria-hidden="true" />
      <div className="reveal-card"><CardTile card={card} /></div>
      <p className="obtained">NEW DRAW · {card.rarity} STAR</p>
      <button className="primary-button" onClick={onClose}>확인</button>
    </div>
  );
}
