import type { Card } from "../types";

export function Stars({ rarity }: { rarity: number }) {
  return (
    <span className="stars" aria-label={`${rarity}성`}>
      {Array.from({ length: rarity }, (_, index) => (
        <svg key={index} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 1.8l2.85 6.05 6.35.95-4.6 4.7 1.1 6.65L12 17.02l-5.7 3.13 1.1-6.65-4.6-4.7 6.35-.95L12 1.8z" />
        </svg>
      ))}
    </span>
  );
}

export function CardTile({ card, compact = false, onClick }: { card: Card; compact?: boolean; onClick?: () => void }) {
  return (
    <article className={`card-tile rarity-${card.rarity} ${compact ? "compact" : ""}`} onClick={onClick}>
      <div className="card-art-wrap">
        <img src={card.image_url} alt={`${card.name} 카드`} className="card-art" />
        {card.quantity !== undefined && <span className="quantity">×{card.quantity}</span>}
      </div>
      <div className="card-meta">
        <h3>{card.name}</h3>
        <span>{card.yp.toLocaleString()} YP</span>
      </div>
      <Stars rarity={card.rarity} />
    </article>
  );
}
