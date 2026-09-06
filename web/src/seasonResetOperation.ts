import { idempotencyKey } from "./api";

export const SEASON_RESET_OPERATION_STORAGE_KEY = "youngho-gacha:season-reset-operation-id";

let memoryOperationId: string | null = null;
let useMemoryFallback = false;

function readStoredOperationId(): string | null {
  if (useMemoryFallback) return memoryOperationId;
  try {
    const stored = localStorage.getItem(SEASON_RESET_OPERATION_STORAGE_KEY);
    memoryOperationId = stored;
    return stored;
  } catch {
    useMemoryFallback = true;
    return memoryOperationId;
  }
}

function persistOperationId(operationId: string) {
  memoryOperationId = operationId;
  try {
    localStorage.setItem(SEASON_RESET_OPERATION_STORAGE_KEY, operationId);
    useMemoryFallback = false;
  } catch {
    useMemoryFallback = true;
  }
}

export function getPendingSeasonResetOperation(): string {
  const pending = readStoredOperationId();
  if (pending) return pending;
  const operationId = idempotencyKey("season-reset");
  persistOperationId(operationId);
  return operationId;
}

export function clearPendingSeasonResetOperation(operationId: unknown) {
  if (typeof operationId !== "string" || !operationId) return;
  if (memoryOperationId === operationId) memoryOperationId = null;
  try {
    if (localStorage.getItem(SEASON_RESET_OPERATION_STORAGE_KEY) === operationId) {
      localStorage.removeItem(SEASON_RESET_OPERATION_STORAGE_KEY);
    }
    useMemoryFallback = false;
  } catch {
    useMemoryFallback = true;
  }
}
