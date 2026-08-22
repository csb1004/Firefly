export type User = {
  id: number;
  discord_id: string;
  username: string;
  display_name: string;
  avatar_url: string;
  warning_acknowledged?: boolean;
  accepts_gifts: boolean;
  accepts_trades: boolean;
  is_admin?: boolean;
};

export type Card = {
  id: string;
  name: string;
  rarity: number;
  yp: number;
  image_url: string;
  quantity?: number;
  available_quantity?: number;
  weight?: number | null;
  active?: boolean;
};

export type Collection = { user_id: number; total_yp: number; cards: Card[] };

export type Catalog = {
  owned_count: number;
  total_count: number;
  cards: Array<Card & { owned: boolean; quantity: number }>;
};

export type DrawStatus = {
  eligible: boolean;
  draws_remaining: number;
  daily_remaining: number;
  bonus_tickets: number;
  four_remaining: number;
  five_remaining: number;
};

export type TradeRoom = {
  id: string;
  status: string;
  inviter_id: number;
  invitee_id: number;
  offer_version: number;
  accepted: Record<string, boolean>;
  offers: Array<{ user_id: number; card_id: string; card_name: string; rarity: number; quantity: number }>;
  requests: Array<{ id: string; requester_id: number; kind: string; card_id?: string; quantity?: number; message?: string }>;
};
