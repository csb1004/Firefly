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

export type Collection = {
  user_id: number;
  total_yp: number;
  base_yp?: number;
  fixed_bonus?: number;
  percent_bonus?: number;
  percent_yp?: number;
  active_sets?: string[];
  cards: Card[];
};

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

export type DrawHistoryItem = {
  id: string;
  draw_number: number;
  drawn_at: string;
  draw_day: string;
  ticket_source: "daily" | "bonus";
  batch_id: string | null;
  batch_position: number | null;
  card_id: string | null;
  card_name: string;
  card_rarity: number;
  card_yp: number;
  image_url: string | null;
};

export type DrawHistoryResponse = {
  page: number;
  page_size: number;
  total: number;
  summary: { total_draws: number; four_remaining: number; five_remaining: number };
  items: DrawHistoryItem[];
};

export type TradeRoom = {
  id: string;
  status: string;
  inviter_id: number;
  invitee_id: number;
  offer_version: number;
  accepted: Record<string, boolean>;
  yp_preview?: Record<string, { before: number; after: number; change: number }>;
  offers: Array<{ user_id: number; card_id: string; card_name: string; rarity: number; quantity: number }>;
  requests: Array<{ id: string; requester_id: number; kind: string; card_id?: string; quantity?: number; message?: string }>;
};

export type SetEffect = {
  id?: string;
  target_scope: "set_members" | "selected_cards" | "rarity" | "collection";
  target_rarity: number | null;
  target_card_ids: string[];
  bonus_target_scope: "set_members" | "selected_cards" | "rarity" | "collection";
  bonus_target_rarity: number | null;
  bonus_target_card_ids: string[];
  count_mode: "once" | "distinct" | "quantity";
  bonus_type: "fixed" | "percent";
  value: number;
  max_count: number | null;
};

export type CardSet = {
  id: string;
  name: string;
  active: boolean;
  member_card_ids: string[];
  effects: SetEffect[];
};

export type SetDefinition = {
  id: string;
  name: string;
  completed: boolean;
  owned_member_count: number;
  required_member_count: number;
  member_cards: Array<Pick<Card, "id" | "name" | "rarity">>;
  yp_bonus: {
    total: number;
    cards: Array<{
      card_id: string;
      card_name: string;
      rarity: number;
      quantity: number;
      base_yp: number;
      fixed_bonus: number;
      percent_bonus: number;
      total_bonus: number;
    }>;
  };
  effects: Array<Omit<SetEffect, "target_card_ids" | "bonus_target_card_ids"> & {
    target_cards: Array<Pick<Card, "id" | "name" | "rarity">>;
    bonus_target_cards: Array<Pick<Card, "id" | "name" | "rarity">>;
  }>;
};

export type AdminCollectionState = {
  user: User;
  total_yp: number;
  cards: Array<Card & { quantity: number; reserved_quantity: number; unlocked: boolean }>;
};
