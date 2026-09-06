# Youngho Gacha Season Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a guarded administrator action that deletes all Youngho Gacha player progression and history while preserving Discord accounts, active logins, card content, and every administrator-configured game setting.

**Architecture:** A focused reset service owns the explicit delete allowlist, locked recount, bonus-ticket reseed, and sole replacement audit row. A per-app asynchronous coordinator drains in-flight card mutations and rejects new ones while the reset transaction holds PostgreSQL advisory and table locks; the admin route commits once and broadcasts `season.reset` after success. A collapsed React danger-zone component previews impact and requires an exact phrase, while the app-level realtime handler remounts stale pages without logging users out.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, PostgreSQL, pytest, React, TypeScript, Vite, Vitest, Testing Library, Discord WebSocket integration.

**Spec:** `docs/superpowers/specs/2026-09-06-youngho-gacha-season-reset-design.md`

## Global Constraints

- Preserve `users`, `web_sessions`, `oauth_attempts`, `rarity_settings`, `cards`, all set tables, `draw_settings`, `image_cleanup`, and `alembic_version` without changing their configured values.
- Delete only the explicit player-progression, draw-history, transfer, trade, notification, WebSocket-ticket, and prior-audit allowlist; never use database-wide `DROP` or `TRUNCATE ... CASCADE`.
- Reset inventory and catalog unlocks together.
- Reissue exactly `draw_settings.new_user_bonus_tickets` bonus tickets to every existing user and make the configured daily allowance immediately available.
- Preserve active web login sessions and account preferences.
- Delete all previous audit rows, then retain exactly one `AdminAudit(action="season.reset")` row for the completed reset.
- Require `SPECIAL_USER_ID`, CSRF, an impact preview in the UI, and the exact confirmation text `영호 가챠 시즌 초기화`.
- Block and drain every mutation that touches resettable progression, content configuration, or WebSocket-ticket rows; keep identity/account actions and read-only POST previews usable because they do not corrupt the reset boundary.
- Broadcast `{"type":"season.reset"}` only after a successful commit.
- Never run the production reset during automated verification or deployment.

## File Structure

- Create `bandi_cards/season_reset.py`: per-app mutation/reset coordinator, domain exceptions, and the FastAPI mutation dependency.
- Create `bandi_cards/services/season_reset.py`: delete allowlist, preview contract, PostgreSQL locks, bonus reseed, and atomic reset statements without an internal commit.
- Create `bandi_cards/routes/admin_reset.py`: administrator preview and execute endpoints plus the single commit/rollback boundary.
- Modify `bandi_cards/app.py`: instantiate a fresh coordinator per app and register the reset router.
- Modify `bandi_cards/routes/auth.py`, `admin_draws.py`, `admin_collections.py`, `admin_sets.py`, `cards.py`, `collections.py`, `draws.py`, `gifts.py`, and `trades.py`: attach the mutation dependency to the 23 writes that touch resettable or configured card-domain data.
- Modify `bandi_cards/realtime/connection_manager.py`: broadcast a global reset event.
- Create `tests/bandi_cards/test_season_reset_coordinator.py`: deterministic coordinator drain/rejection tests.
- Create `tests/bandi_cards/test_season_reset_service.py`: full-table preserve/delete/reseed/rollback tests on SQLite.
- Create `tests/bandi_cards/test_season_reset_postgres.py`: real PostgreSQL lock, rollback, and FK-order coverage.
- Modify `.github/workflows/ci.yml`: run the opt-in PostgreSQL reset test against an ephemeral CI database.
- Create `tests/bandi_cards/test_admin_season_reset.py`: authorization, confirmation, API contract, overlap, maintenance, and realtime tests.
- Modify `tests/bandi_cards/test_trades.py`: WebSocket maintenance-boundary regressions.
- Create `tests/bandi_cards/test_connection_manager.py`: global broadcast coverage.
- Modify `tests/test_card_commands.py`: bot ranking behavior after reset.
- Modify `tests/test_discord_profiles.py`: preserved accounts remain eligible for bot profile sync after reset.
- Create `web/src/components/AdminSeasonReset.tsx`: collapsed inline danger-zone UI.
- Create `web/src/components/AdminSeasonReset.test.tsx`: component interaction and API-call tests.
- Modify `web/src/types.ts`: exact reset preview/result DTOs.
- Modify `web/src/App.tsx`: mount the danger zone, own the success notice, and handle `season.reset` by replacing the route and remounting page data.
- Create `web/src/App.test.tsx`: realtime reset behavior and same-route refresh regression tests.
- Modify `web/src/styles.css`: responsive danger-zone and reset-notice styles.
- Modify `docs/operations/bandi-card-site.md`: administrator reset runbook and post-reset checks.

---

### Task 1: Per-app season reset coordinator

**Files:**
- Create: `bandi_cards/season_reset.py`
- Create: `tests/bandi_cards/test_season_reset_coordinator.py`

**Interfaces:**
- Produces: `SeasonResetInProgress`, `SeasonResetAlreadyRunning`, `SeasonResetCoordinator.is_resetting`, `SeasonResetCoordinator.mutation()`, `SeasonResetCoordinator.reset()`, and `track_season_mutation(request: Request)`.
- Consumes: `request.app.state.season_reset_coordinator`, initialized in Task 3.

- [ ] **Step 1: Write failing coordinator tests**

```python
import asyncio

import pytest

from bandi_cards.season_reset import (
    SeasonResetAlreadyRunning,
    SeasonResetCoordinator,
    SeasonResetInProgress,
)


def test_reset_drains_active_mutation_and_rejects_new_mutation():
    async def scenario():
        coordinator = SeasonResetCoordinator()
        mutation_entered = asyncio.Event()
        release_mutation = asyncio.Event()
        reset_entered = asyncio.Event()

        async def mutation():
            async with coordinator.mutation():
                mutation_entered.set()
                await release_mutation.wait()

        async def reset():
            async with coordinator.reset():
                reset_entered.set()

        mutation_task = asyncio.create_task(mutation())
        await mutation_entered.wait()
        reset_task = asyncio.create_task(reset())
        await asyncio.sleep(0)
        assert coordinator.is_resetting is True
        assert reset_entered.is_set() is False
        with pytest.raises(SeasonResetInProgress):
            async with coordinator.mutation():
                pass
        release_mutation.set()
        await mutation_task
        await reset_task
        assert reset_entered.is_set() is True
        assert coordinator.is_resetting is False

    asyncio.run(scenario())


def test_overlapping_reset_is_rejected_and_exception_releases_state():
    async def scenario():
        coordinator = SeasonResetCoordinator()
        async with coordinator.reset():
            with pytest.raises(SeasonResetAlreadyRunning):
                async with coordinator.reset():
                    pass
        with pytest.raises(RuntimeError):
            async with coordinator.reset():
                raise RuntimeError("injected")
        assert coordinator.is_resetting is False

    asyncio.run(scenario())


def test_cancelled_reset_wait_releases_maintenance_state():
    async def scenario():
        coordinator = SeasonResetCoordinator()
        mutation_entered = asyncio.Event()
        release_mutation = asyncio.Event()

        async def mutation():
            async with coordinator.mutation():
                mutation_entered.set()
                await release_mutation.wait()

        async def enter_reset():
            async with coordinator.reset():
                pass

        mutation_task = asyncio.create_task(mutation())
        await mutation_entered.wait()
        reset_task = asyncio.create_task(enter_reset())
        await asyncio.sleep(0)
        reset_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reset_task
        assert coordinator.is_resetting is False
        release_mutation.set()
        await mutation_task

    asyncio.run(scenario())
```

This regression ensures cancellation while draining active work cannot leave the site permanently in maintenance mode.

- [ ] **Step 2: Run the coordinator tests and verify RED**

Run: `python -m pytest tests/bandi_cards/test_season_reset_coordinator.py -q`

Expected: collection or assertion failure because the coordinator module and interfaces do not exist.

- [ ] **Step 3: Implement the coordinator and HTTP dependency**

```python
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import HTTPException, Request, status


RESET_IN_PROGRESS_MESSAGE = "시즌 초기화가 진행 중입니다. 잠시 후 다시 시도해주세요."


class SeasonResetInProgress(RuntimeError):
    pass


class SeasonResetAlreadyRunning(RuntimeError):
    pass


class SeasonResetCoordinator:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._is_resetting = False
        self._active_mutations = 0

    @property
    def is_resetting(self) -> bool:
        return self._is_resetting

    @asynccontextmanager
    async def mutation(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._is_resetting:
                raise SeasonResetInProgress
            self._active_mutations += 1
        try:
            yield
        finally:
            async with self._condition:
                self._active_mutations -= 1
                self._condition.notify_all()

    @asynccontextmanager
    async def reset(self) -> AsyncIterator[None]:
        async with self._condition:
            if self._is_resetting:
                raise SeasonResetAlreadyRunning
            self._is_resetting = True
        try:
            async with self._condition:
                await self._condition.wait_for(lambda: self._active_mutations == 0)
            yield
        finally:
            async with self._condition:
                self._is_resetting = False
                self._condition.notify_all()


async def track_season_mutation(request: Request) -> AsyncIterator[None]:
    coordinator = request.app.state.season_reset_coordinator
    try:
        async with coordinator.mutation():
            yield
    except SeasonResetInProgress as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, RESET_IN_PROGRESS_MESSAGE) from exc
```

- [ ] **Step 4: Run the coordinator tests and verify GREEN**

Run: `python -m pytest tests/bandi_cards/test_season_reset_coordinator.py -q`

Expected: all coordinator tests pass.

- [ ] **Step 5: Commit the coordinator**

```powershell
git add -- bandi_cards/season_reset.py tests/bandi_cards/test_season_reset_coordinator.py
git commit -m "feat(cards): coordinate season reset writes"
```

---

### Task 2: Locked preview and reset service

**Files:**
- Create: `bandi_cards/services/season_reset.py`
- Create: `tests/bandi_cards/test_season_reset_service.py`
- Create: `tests/bandi_cards/test_season_reset_postgres.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: all SQLAlchemy models in the explicit reset and preserve lists; `DrawSetting(id=1)`; `validate_probability_configuration(db, probabilities)`.
- Produces: `CONFIRMATION_TEXT`, `SeasonResetLockUnavailable`, `SeasonResetConfigurationInvalid`, `preview_season_reset(db: Session) -> dict`, and `execute_season_reset(db: Session, admin_id: int) -> dict`.
- Contract: neither service function commits; `execute_season_reset` returns authoritative counts captured after database locks.

- [ ] **Step 1: Write a complete seeded reset test**

Create a `_seed_season_data(factory)` helper that inserts two `User` rows; updates the five existing `RaritySetting` rows and singleton `DrawSetting`; inserts one active `Card` in every rarity so the preserved probability configuration is valid; and inserts a `CardSet`, member, effect, both selected-target rows, `WebSession`, `OAuthAttempt`, `ImageCleanup`, plus at least one row for every reset model. Reuse valid constructors from `bandi_cards/models.py`; create the trade room before its offer/request and draw history before its five-star event.

```python
def test_reset_deletes_only_season_data_and_reissues_configured_bonus(web_db):
    seeded = _seed_season_data(web_db, daily_draws=3, new_user_bonus_tickets=7)
    with web_db() as db:
        preview = preview_season_reset(db)
        result = execute_season_reset(db, seeded.admin_id)
        db.commit()

    assert preview["grant"] == {
        "eligible_users": 2,
        "tickets_per_user": 7,
        "total_tickets": 14,
    }
    assert result["grant"] == {
        "granted_users": 2,
        "tickets_per_user": 7,
        "total_tickets": 14,
    }

    with web_db() as db:
        empty_models = tuple(model for model in RESET_MODELS if model not in (DrawWallet, AdminAudit))
        for model in empty_models:
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 2
        assert db.scalar(select(func.count()).select_from(WebSession)) == 1
        assert db.scalar(select(func.count()).select_from(OAuthAttempt)) == 1
        assert db.scalar(select(func.count()).select_from(Card)) == 5
        assert db.scalar(select(func.count()).select_from(CardSet)) == 1
        assert db.scalar(select(func.count()).select_from(RaritySetting)) == 5
        assert db.get(DrawSetting, 1).daily_draws == 3
        assert db.get(DrawSetting, 1).new_user_bonus_tickets == 7
        wallets = db.scalars(select(DrawWallet).order_by(DrawWallet.user_id)).all()
        assert [wallet.bonus_tickets for wallet in wallets] == [7, 7]
        audits = db.scalars(select(AdminAudit)).all()
        assert len(audits) == 1
        assert audits[0].action == "season.reset"
        assert audits[0].admin_id == seeded.admin_id
        assert audits[0].target_type == "season"
        assert audits[0].target_id == result["completed_at"]
        assert audits[0].id == result["audit_id"]
        details = json.loads(audits[0].details_json)
        assert details == {
            "delete_counts": result["delete_counts"],
            "grant": result["grant"],
            "preserved": result["preserved"],
        }
```

Also assert the original card and user/profile fields, every set effect field, every rarity probability, `WebSession`, `OAuthAttempt`, and `ImageCleanup` row remain unchanged. Assert `draw_ticket_status(db, user_id)` reports `daily_remaining == 3` and `bonus_tickets == 7`; separately assert `db.get(DrawState, user_id) is None` and `draw_counters(None) == (0, 0)` for reset pity.

- [ ] **Step 2: Write zero-benefit, preview, and rollback tests**

```python
def test_zero_new_user_benefit_creates_no_wallet_rows(web_db):
    seeded = _seed_season_data(web_db, daily_draws=1, new_user_bonus_tickets=0)
    with web_db() as db:
        execute_season_reset(db, seeded.admin_id)
        db.commit()
    with web_db() as db:
        assert db.scalar(select(func.count()).select_from(DrawWallet)) == 0


def test_preview_is_read_only_and_reports_exact_counts(web_db):
    _seed_season_data(web_db, daily_draws=2, new_user_bonus_tickets=4)
    with web_db() as db:
        before = _table_counts(db)
        preview = preview_season_reset(db)
        db.rollback()
    with web_db() as db:
        assert _table_counts(db) == before
    assert preview["preserved"]["draw_settings"] == {
        "daily_draws": 2,
        "new_user_bonus_tickets": 4,
    }


def test_reset_failure_after_reseed_rolls_back_every_change(web_db, monkeypatch):
    seeded = _seed_season_data(web_db, daily_draws=3, new_user_bonus_tickets=7)
    before = _full_state_snapshot(web_db)
    monkeypatch.setattr(season_reset, "_append_reset_audit", lambda *args: (_ for _ in ()).throw(RuntimeError("injected")))
    with web_db() as db:
        with pytest.raises(RuntimeError, match="injected"):
            execute_season_reset(db, seeded.admin_id)
        db.rollback()
    assert _full_state_snapshot(web_db) == before
```

Make `_full_state_snapshot` serialize every table's rows in primary-key order, including user preferences/profile sync fields, session token/expiry, OAuth verifier/expiry, inventory quantities/reservations, wallet balances, and audit JSON—not just table counts. Add `test_lock_unavailable_changes_nothing` by monkeypatching the private PostgreSQL lock helper to raise `SeasonResetLockUnavailable` and comparing full snapshots. Add missing-`DrawSetting` and invalid-rarity tests against both `preview_season_reset` and `execute_season_reset`; each must raise `SeasonResetConfigurationInvalid` before any delete.

- [ ] **Step 3: Run the service tests and verify RED**

Run: `python -m pytest tests/bandi_cards/test_season_reset_service.py tests/bandi_cards/test_season_reset_postgres.py -q`

Expected: SQLite tests fail because the preview/reset service is absent; the PostgreSQL module skips locally when `TEST_POSTGRES_URL` is absent.

- [ ] **Step 4: Implement the exact contracts and delete allowlist**

Use a static child-first tuple:

```python
RESET_MODELS = (
    FiveStarEvent,
    DrawHistory,
    DrawBatch,
    TradeOffer,
    TradeRequest,
    TradeRoom,
    Gift,
    DiscardEvent,
    Inventory,
    CatalogUnlock,
    DrawState,
    DailyDrawAllowance,
    DrawWallet,
    WebSocketTicket,
    NotificationOutbox,
    ProbabilityAudit,
    AdminAudit,
)
```

The preview contract is fixed as follows:

```python
{
    "delete_counts": {model.__tablename__: int_count for model in RESET_MODELS},
    "summary": {
        "inventory_copies": int,
        "trade_records": int,
        "audit_records": int,
    },
    "preserved": {
        "users": int,
        "cards": int,
        "card_sets": int,
        "rarity_settings": int,
        "image_cleanup": int,
        "draw_settings": {
            "daily_draws": int,
            "new_user_bonus_tickets": int,
        },
    },
    "grant": {
        "eligible_users": int,
        "tickets_per_user": int,
        "total_tickets": int,
    },
}
```

The execute result uses the identical `delete_counts`, `summary`, and `preserved` objects, with this exact completion tail:

```python
{
    "grant": {
        "granted_users": int,
        "tickets_per_user": int,
        "total_tickets": int,
    },
    "completed_at": str,
    "audit_id": str,
}
```

Compute summaries exactly as follows: `inventory_copies` is `SUM(inventory.quantity)`, `trade_records` is the sum of row counts in all three trade tables, and `audit_records` is the sum of the two prior audit tables. `eligible_users`/`granted_users` is the number of preserved `users`, including the administrator.

Both preview and execute must call one `_load_and_validate_configuration(db)` helper. It loads `DrawSetting(id=1)`, calls `base_probabilities(db)`, and passes that result to `validate_probability_configuration(db, probabilities)`. Convert a missing setting row or its validation `HTTPException` into `SeasonResetConfigurationInvalid` without deleting anything. On PostgreSQL execute, acquire one fixed two-key transaction advisory lock and then lock the reset tables in the same deterministic order, plus `users IN SHARE MODE` and `draw_settings IN SHARE MODE`:

```python
locked = db.scalar(text("SELECT pg_try_advisory_xact_lock(:namespace, :operation)"), {
    "namespace": 1947147369,
    "operation": 1,
})
if not locked:
    raise SeasonResetLockUnavailable
db.execute(text("LOCK TABLE users, draw_settings IN SHARE MODE"))
db.execute(text("LOCK TABLE five_star_events, draw_history, draw_batches, trade_offers, trade_requests, trade_rooms, gifts, discard_events, inventory, catalog_unlocks, draw_states, daily_draw_allowances, draw_wallets, websocket_tickets, notification_outbox, probability_audit, admin_audit IN ACCESS EXCLUSIVE MODE"))
```

Skip only these PostgreSQL-specific statements when `db.get_bind().dialect.name == "sqlite"`. Capture all counts after locks, delete each model with `db.execute(delete(model))`, bulk insert one `DrawWallet` per user only when the configured benefit is positive, and flush. Append the sole audit row with `action="season.reset"`, `target_type="season"`, `target_id=completed_at.isoformat()`, the executing `admin_id`, `created_at=completed_at`, and deterministic `details_json=json.dumps({...}, ensure_ascii=False, sort_keys=True)` containing the delete counts, grant object, and preserved object. Flush again to obtain `audit.id`; return its ID and the same ISO completion timestamp. Do not call `commit()`.

- [ ] **Step 5: Add a real PostgreSQL transaction-boundary test**

In `tests/bandi_cards/test_season_reset_postgres.py`, skip unless `TEST_POSTGRES_URL` is set and reject any configured database name that does not end in `_test`. Build a dedicated engine, recreate only `Base.metadata` in that ephemeral database, and seed valid reset data. With two independent sessions:

1. Run `execute_season_reset(first, admin_id)` without committing so the advisory lock and deletes remain transactional.
2. Assert `execute_season_reset(second, admin_id)` immediately raises `SeasonResetLockUnavailable` and changes nothing in the second transaction.
3. Roll back the first session and assert all seeded rows and field values are restored.
4. Open a fresh session, execute and commit, then assert PostgreSQL enforces the same delete, reseed, preserve, and sole-audit result as SQLite.

Configure the backend CI job with a `postgres:16` service database named `youngho_test`, health checks, and `TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/youngho_test`. Do not set production `DATABASE_URL` in CI.

- [ ] **Step 6: Run service tests and verify GREEN**

Run: `python -m pytest tests/bandi_cards/test_season_reset_service.py tests/bandi_cards/test_season_reset_postgres.py -q`

Expected: all SQLite service tests pass; PostgreSQL runs in CI and otherwise reports one intentional skip.

- [ ] **Step 7: Commit the reset service**

```powershell
git add -- bandi_cards/services/season_reset.py tests/bandi_cards/test_season_reset_service.py tests/bandi_cards/test_season_reset_postgres.py .github/workflows/ci.yml
git commit -m "feat(cards): reset season data atomically"
```

---

### Task 3: Administrator preview and execute API

**Files:**
- Create: `bandi_cards/routes/admin_reset.py`
- Modify: `bandi_cards/app.py:8-48`
- Create: `tests/bandi_cards/test_admin_season_reset.py`

**Interfaces:**
- Consumes: `SeasonResetCoordinator.reset()`, `preview_season_reset`, `execute_season_reset`, `require_admin`, and `require_admin_csrf`.
- Produces: `GET /api/admin/season-reset/preview` and `POST /api/admin/season-reset`.
- POST body: `{"confirmation": "영호 가챠 시즌 초기화"}`.
- POST result: authoritative reset payload plus `completed_at` and `audit_id`.

- [ ] **Step 1: Write failing authorization and contract tests**

```python
def test_non_admin_cannot_preview_or_execute_reset(signed_in):
    client, _factory, _user_id, csrf = signed_in
    client.post("/api/me/warning", headers={"X-CSRF-Token": csrf})
    assert client.get("/api/admin/season-reset/preview").status_code == 403
    assert client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT},
    ).status_code == 403


def test_reset_requires_csrf_and_exact_confirmation(admin_signed_in):
    client, _factory, _admin_id, csrf = admin_signed_in
    assert client.post("/api/admin/season-reset", json={"confirmation": CONFIRMATION_TEXT}).status_code == 403
    response = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": "시즌 초기화"},
    )
    assert response.status_code == 400


def test_admin_preview_and_execute_preserve_session(admin_signed_in):
    client, factory, admin_id, csrf = admin_signed_in
    _seed_season_data(factory, admin_id=admin_id, daily_draws=3, new_user_bonus_tickets=7)
    preview = client.get("/api/admin/season-reset/preview")
    assert preview.status_code == 200
    reset = client.post(
        "/api/admin/season-reset",
        headers={"X-CSRF-Token": csrf},
        json={"confirmation": CONFIRMATION_TEXT},
    )
    assert reset.status_code == 200
    assert reset.json()["grant"]["tickets_per_user"] == 7
    assert client.get("/api/auth/me").status_code == 200
```

Add an overlap test that holds the first `_commit_reset` call with `threading.Event`, sends a second exact-confirmation request, expects `409`, releases the first request, and asserts only one successful response and one `season.reset` audit row. Keep this distinct from the Task 2 database-lock failure test: this one verifies the per-app coordinator and HTTP mapping.

- [ ] **Step 2: Run API tests and verify RED**

Run: `python -m pytest tests/bandi_cards/test_admin_season_reset.py -q`

Expected: 404 failures because the reset router is not registered.

- [ ] **Step 3: Implement the router and one commit boundary**

```python
class SeasonResetBody(BaseModel):
    confirmation: str


def _commit_reset(factory, admin_id: int) -> dict:
    with factory() as db:
        try:
            result = execute_season_reset(db, admin_id)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


async def _complete_reset_transaction(factory, admin_id: int) -> dict:
    operation = asyncio.create_task(asyncio.to_thread(_commit_reset, factory, admin_id))
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Repeated request cancellation must not outlive the DB worker.
            continue
    return operation.result()


@router.get("/preview")
def preview(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    try:
        return preview_season_reset(db)
    except SeasonResetConfigurationInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.post("")
async def reset_season(body: SeasonResetBody, request: Request, admin: User = Depends(require_admin_csrf)) -> dict:
    if body.confirmation != CONFIRMATION_TEXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "확인 문구가 일치하지 않습니다.")
    coordinator = request.app.state.season_reset_coordinator
    try:
        async with coordinator.reset():
            result = await _complete_reset_transaction(request.app.state.session_factory, admin.id)
    except (SeasonResetAlreadyRunning, SeasonResetLockUnavailable) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "시즌 초기화가 이미 진행 중입니다.") from exc
    except SeasonResetConfigurationInvalid as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return result
```

Instantiate `SeasonResetCoordinator()` inside `create_app()` so each test app is isolated and import/register `admin_reset_router`. Generate `completed_at` and `audit_id` inside the transaction so the response and sole audit row agree.

Add a cancellation regression around `_complete_reset_transaction`: cancel the awaiting task twice while a monkeypatched `_commit_reset` is held on a `threading.Event`, assert after each cancellation that the task is unfinished and the coordinator remains active, release the worker, then assert the task completes normally. This prevents repeated disconnect/shutdown cancellation from releasing maintenance while its database thread can still commit.

- [ ] **Step 4: Run API tests and verify GREEN**

Run: `python -m pytest tests/bandi_cards/test_admin_season_reset.py -q`

Expected: authorization, confirmation, session-preservation, and success contract tests pass.

- [ ] **Step 5: Commit the API boundary**

```powershell
git add -- bandi_cards/routes/admin_reset.py bandi_cards/app.py tests/bandi_cards/test_admin_season_reset.py
git commit -m "feat(cards): expose guarded season reset API"
```

---

### Task 4: Guard all card mutations and WebSocket DB transitions

**Files:**
- Modify: `bandi_cards/routes/admin_draws.py`
- Modify: `bandi_cards/routes/auth.py`
- Modify: `bandi_cards/routes/admin_collections.py`
- Modify: `bandi_cards/routes/admin_sets.py`
- Modify: `bandi_cards/routes/cards.py`
- Modify: `bandi_cards/routes/collections.py`
- Modify: `bandi_cards/routes/draws.py`
- Modify: `bandi_cards/routes/gifts.py`
- Modify: `bandi_cards/routes/trades.py`
- Modify: `tests/bandi_cards/test_admin_season_reset.py`
- Modify: `tests/bandi_cards/test_trades.py`

**Interfaces:**
- Consumes: `track_season_mutation` and the app-local `SeasonResetCoordinator` from Task 1.
- Produces: a 503 maintenance response for the 23 writes that touch resettable/configured card data; login, logout, CSRF, account preferences, warning acknowledgement, and read-only previews remain available.

- [ ] **Step 1: Write failing mutation-gate tests**

Use `asyncio.Event` and a monkeypatched `_commit_reset` to hold an admin reset request open. While held, assert representative endpoints from each router return 503, then release and assert the reset completes. Directly inspect route dependencies to assert all 23 decorators contain `track_season_mutation`.

```python
GUARDED_ROUTES = {
    ("POST", "/api/auth/websocket-ticket"),
    ("PUT", "/api/admin/draw-settings"),
    ("POST", "/api/admin/users/{user_id}/draw-tickets/grant"),
    ("POST", "/api/admin/users/{user_id}/draw-tickets/reset-today"),
    ("PUT", "/api/admin/users/{user_id}/inventory/{card_id}"),
    ("PUT", "/api/admin/users/{user_id}/catalog/{card_id}"),
    ("POST", "/api/admin/sets"),
    ("PUT", "/api/admin/sets/{set_id}"),
    ("DELETE", "/api/admin/sets/{set_id}"),
    ("POST", "/api/admin/cards"),
    ("PUT", "/api/admin/cards/{card_id}"),
    ("PUT", "/api/admin/probabilities"),
    ("DELETE", "/api/admin/cards/{card_id}"),
    ("POST", "/api/collection/discard"),
    ("POST", "/api/draw"),
    ("POST", "/api/draw/ten"),
    ("POST", "/api/gifts"),
    ("POST", "/api/trades/invite"),
    ("POST", "/api/trades/{room_id}/accept-invite"),
    ("PUT", "/api/trades/{room_id}/offer"),
    ("POST", "/api/trades/{room_id}/request"),
    ("POST", "/api/trades/{room_id}/accept"),
    ("POST", "/api/trades/{room_id}/cancel"),
}
```

Also assert these remain unguarded: `/api/auth/csrf`, `/api/auth/logout`, `/api/me/warning`, `/api/me/settings`, `/api/collection/discard/preview`, `/api/gifts/preview`, reset preview, and reset execution. These are deliberately narrower exceptions to the design's shorthand “block new writes”: they preserve login/account continuity or are logically read-only, while PostgreSQL user-table locking safely serializes the rare overlapping profile update.

- [ ] **Step 2: Write failing WebSocket maintenance tests**

Run the reset context in a helper thread and synchronize it with `threading.Event`, so the test uses the real public coordinator interface rather than mutating private state:

```python
def test_websocket_handshake_closes_with_1013_during_reset(web_client):
    entered = threading.Event()
    release = threading.Event()

    def hold_reset() -> None:
        async def scenario() -> None:
            async with web_client.app.state.season_reset_coordinator.reset():
                entered.set()
                await asyncio.to_thread(release.wait)
        asyncio.run(scenario())

    thread = threading.Thread(target=hold_reset)
    thread.start()
    assert entered.wait(timeout=2)
    try:
        with pytest.raises(WebSocketDisconnect) as caught:
            with web_client.websocket_connect("/ws?ticket=unused"):
                pass
        assert caught.value.code == 1013
    finally:
        release.set()
        thread.join(timeout=2)
```

Add a second test that opens a valid socket before the reset, then proves the reset context enters without waiting for the socket receive loop to finish.

- [ ] **Step 3: Run the gate tests and verify RED**

Run: `python -m pytest tests/bandi_cards/test_admin_season_reset.py tests/bandi_cards/test_trades.py -q`

Expected: guarded route assertions fail and the WebSocket remains connectable during reset.

- [ ] **Step 4: Attach the dependency to exactly 23 endpoint decorators**

For every route in `GUARDED_ROUTES`, use this established FastAPI form:

```python
@router.post("/draw", dependencies=[Depends(track_season_mutation)])
```

Keep preview endpoints and account/auth endpoints unguarded. Do not use a blanket HTTP-method middleware because Discord OAuth callbacks write on GET and must remain available.

- [ ] **Step 5: Guard short WebSocket database sections**

At handshake, close with code `1013` when `coordinator.is_resetting`. Wrap ticket consumption and initial reconnect restoration in `coordinator.mutation()`. In the socket `finally`, enter `coordinator.mutation()` before `mark_user_reconnecting`; if reset has started, skip that write and do not schedule an expiry task. Pass the coordinator into `expire_disconnect`, enter `coordinator.mutation()` only around its short `cancel_user_rooms` transaction, and return without a write if reset has started. Never hold `mutation()` around the socket receive loop or its 15-second delay.

```python
coordinator = websocket.app.state.season_reset_coordinator
if coordinator.is_resetting:
    await websocket.close(code=1013)
    return
try:
    async with coordinator.mutation():
        with factory() as db:
            record = db.get(WebSocketTicket, token_hash(ticket))
            if record is None or record.consumed_at is not None or as_utc(record.expires_at) <= utcnow():
                raise InvalidWebSocketTicket
            record.consumed_at = utcnow()
            user_id = record.user_id
            db.commit()
except SeasonResetInProgress:
    await websocket.close(code=1013)
    return
except InvalidWebSocketTicket:
    await websocket.close(code=1008)
    return
```

Define `InvalidWebSocketTicket` as a private exception in `trades.py`. After `manager.connect`, enter a second short `mutation()` block around `restore_user_rooms`; handle a reset race by leaving the accepted socket connected but skipping restoration, because every pre-reset trade room is about to be removed.

- [ ] **Step 6: Run gate and WebSocket tests and verify GREEN**

Run: `python -m pytest tests/bandi_cards/test_admin_season_reset.py tests/bandi_cards/test_trades.py -q`

Expected: all route coverage, 503, 409, handshake, and existing trade tests pass.

- [ ] **Step 7: Commit the mutation boundary**

```powershell
git add -- bandi_cards/routes/auth.py bandi_cards/routes/admin_draws.py bandi_cards/routes/admin_collections.py bandi_cards/routes/admin_sets.py bandi_cards/routes/cards.py bandi_cards/routes/collections.py bandi_cards/routes/draws.py bandi_cards/routes/gifts.py bandi_cards/routes/trades.py tests/bandi_cards/test_admin_season_reset.py tests/bandi_cards/test_trades.py
git commit -m "feat(cards): pause writes during season reset"
```

---

### Task 5: Broadcast reset completion to every live client

**Files:**
- Modify: `bandi_cards/realtime/connection_manager.py`
- Modify: `bandi_cards/routes/admin_reset.py`
- Create: `tests/bandi_cards/test_connection_manager.py`
- Modify: `tests/bandi_cards/test_admin_season_reset.py`

**Interfaces:**
- Produces: `ConnectionManager.broadcast_all(message: dict) -> None`.
- Consumes: the committed reset result from Task 3.

- [ ] **Step 1: Write failing global-broadcast tests**

```python
def test_broadcast_all_sends_once_to_every_connected_user():
    async def scenario():
        manager = ConnectionManager()
        first = FakeWebSocket()
        second = FakeWebSocket()
        await manager.connect(1, first)
        await manager.connect(2, second)
        await manager.broadcast_all({"type": "season.reset"})
        assert first.sent == [{"type": "season.reset"}]
        assert second.sent == [{"type": "season.reset"}]
    asyncio.run(scenario())
```

In the admin API test, monkeypatch the module-level manager and assert the event is absent after an injected rollback but present once after a committed success. Add a third case where `broadcast_all` raises after commit: the endpoint must still return the committed `200` result, retain the sole audit row, and log the notification failure with `logger.exception`.

- [ ] **Step 2: Run broadcast tests and verify RED**

Run: `python -m pytest tests/bandi_cards/test_connection_manager.py tests/bandi_cards/test_admin_season_reset.py -q`

Expected: failure because `broadcast_all` is absent.

- [ ] **Step 3: Implement global broadcast and post-commit emission**

```python
async def broadcast_all(self, message: dict) -> None:
    await self.send_many(list(self.connections), message)
```

Modify the successful tail of `reset_season` only after `_complete_reset_transaction` returns:

```python
try:
    await manager.broadcast_all({"type": "season.reset"})
except Exception:
    logger.exception("Season reset broadcast failed")
return result
```

Individual failed sockets are already removed by `send()`.

- [ ] **Step 4: Run broadcast tests and verify GREEN**

Run: `python -m pytest tests/bandi_cards/test_connection_manager.py tests/bandi_cards/test_admin_season_reset.py -q`

Expected: successful commit emits one event; rollback emits none.

- [ ] **Step 5: Commit realtime completion**

```powershell
git add -- bandi_cards/realtime/connection_manager.py bandi_cards/routes/admin_reset.py tests/bandi_cards/test_connection_manager.py tests/bandi_cards/test_admin_season_reset.py
git commit -m "feat(cards): announce season reset completion"
```

---

### Task 6: Inline administrator danger zone

**Files:**
- Create: `web/src/components/AdminSeasonReset.tsx`
- Create: `web/src/components/AdminSeasonReset.test.tsx`
- Modify: `web/src/types.ts:134-138`
- Modify: `web/src/App.tsx:1-207`
- Modify: `web/src/styles.css:67-89`

**Interfaces:**
- Consumes: reset preview and execute API contracts from Task 3.
- Produces: `AdminSeasonReset({ onCompleted }: { onCompleted: (result: SeasonResetResult) => void })`.

- [ ] **Step 1: Add exact TypeScript DTOs and failing collapsed-state tests**

```typescript
export type SeasonResetPreserved = {
  users: number;
  cards: number;
  card_sets: number;
  rarity_settings: number;
  image_cleanup: number;
  draw_settings: { daily_draws: number; new_user_bonus_tickets: number };
};

export type SeasonResetPreview = {
  delete_counts: Record<string, number>;
  summary: { inventory_copies: number; trade_records: number; audit_records: number };
  preserved: SeasonResetPreserved;
  grant: { eligible_users: number; tickets_per_user: number; total_tickets: number };
};

export type SeasonResetResult = Omit<SeasonResetPreview, "grant"> & {
  grant: { granted_users: number; tickets_per_user: number; total_tickets: number };
  completed_at: string;
  audit_id: string;
};
```

```tsx
it("keeps destructive controls hidden until the administrator previews impact", async () => {
  render(<AdminSeasonReset onCompleted={vi.fn()} />);
  expect(screen.getByRole("button", { name: "위험 구역 열기" })).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByLabelText("확인 문구")).not.toBeInTheDocument();
  expect(api).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "위험 구역 열기" }));
  fireEvent.click(screen.getByRole("button", { name: "초기화 대상 확인" }));
  await screen.findByText("되돌릴 수 없습니다");
  expect(api).toHaveBeenCalledWith("/api/admin/season-reset/preview");
});
```

- [ ] **Step 2: Add failing confirmation, duplicate-click, error, and success tests**

Mock the exact preview payload. Assert every delete/preserve category and both configured draw values render. Assert the execute button stays disabled for `시즌 초기화`, enables only for `영호 가챠 시즌 초기화`, sends exactly one POST with CSRF enabled during rapid clicks, retains preview on failure, and calls `onCompleted(result)` once on success.

```typescript
expect(api).toHaveBeenCalledWith("/api/admin/season-reset", {
  method: "POST",
  body: JSON.stringify({ confirmation: "영호 가챠 시즌 초기화" }),
}, true);
```

- [ ] **Step 3: Run component tests and verify RED**

Run from `web`: `npm test -- src/components/AdminSeasonReset.test.tsx`

Expected: module-not-found failure because the component does not exist.

- [ ] **Step 4: Implement the focused component and mount it last**

Keep local state limited to `expanded`, `preview`, `confirmation`, `busy`, and `error`. Render only a compact toggle while collapsed. After preview, render separate `초기화 대상` and `보존 대상` grids, the configured daily/new-user values, irreversible warning, labeled input, and disabled danger button. Clear confirmation when the zone closes.

Use a fixed Korean label map for every returned reset table (`인벤토리`, `도감 해금`, `천장`, `추가 뽑기권`, `일일 지급`, `뽑기 묶음`, `뽑기 기록`, `5성 기록`, `선물`, `버리기`, `거래방`, `거래 제안`, `추가 요구`, `알림`, `실시간 접속권`, `확률 감사`, `관리 감사`) rather than exposing raw SQL table names. Show inventory copy total, trade-record total, and prior-audit total as the prominent summary.

Import the component into `App.tsx` and render it after `.admin-card-list`, making it the final section in `AdminPage`. Thread an `onSeasonReset` callback prop from `App` through `AdminPage`; Task 7 supplies its behavior.

- [ ] **Step 5: Add responsive styles**

Add `.season-reset-zone`, `.season-reset-toggle`, `.season-reset-counts`, `.season-reset-preserved`, `.season-reset-confirmation`, and `.season-reset-status` rules. Use the existing danger palette, keep warning and controls inline rather than in a popup, and collapse both grids/actions to one column inside the existing mobile media query.

- [ ] **Step 6: Run component tests and build**

Run from `web`:

```powershell
npm test -- src/components/AdminSeasonReset.test.tsx
npm run build
```

Expected: component tests pass and TypeScript/Vite build exits 0.

- [ ] **Step 7: Commit the danger zone**

```powershell
git add -- web/src/components/AdminSeasonReset.tsx web/src/components/AdminSeasonReset.test.tsx web/src/types.ts web/src/App.tsx web/src/styles.css
git commit -m "feat(cards): add season reset danger zone"
```

---

### Task 7: Realtime client refresh and global completion notice

**Files:**
- Modify: `web/src/App.tsx:16-253`
- Create: `web/src/App.test.tsx`

**Interfaces:**
- Consumes: `season.reset` WebSocket event and `SeasonResetResult` from Task 6.
- Produces: an app-owned `seasonEpoch`, replace-style navigation, a short deduplication window for the initiating administrator's POST/WebSocket race, and a dismissible reset notice passed into `Shell`.

- [ ] **Step 1: Write failing reset-event navigation test**

Mock `api` and `openRealtime`, capture the realtime callback, start history at `/trade/room-1`, and return an acknowledged admin from `/api/auth/me`.

```tsx
it("replaces a stale trade route and reloads global data after season reset", async () => {
  history.replaceState({}, "", "/trade/room-1");
  render(<App />);
  await waitFor(() => expect(openRealtime).toHaveBeenCalled());
  act(() => realtimeHandler({ type: "season.reset" }));
  expect(location.pathname).toBe("/");
  expect(screen.getByText("새 시즌이 시작되었습니다.")).toBeInTheDocument();
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/feed/five-stars"));
  await waitFor(() => expect(api).toHaveBeenCalledWith("/api/draw/status"));
});
```

Spy on `history.replaceState` and assert `pushState` is not used for the reset transition, so browser Back cannot reopen a deleted trade room.

- [ ] **Step 2: Write the same-path remount regression test**

Start at `/`, record the initial `/api/draw/status` call count, emit `season.reset`, and assert the call count increases. Also seed a visible invite and feed response, then verify both stale items disappear and the feed is fetched again.

- [ ] **Step 3: Run App tests and verify RED**

Run from `web`: `npm test -- src/App.test.tsx`

Expected: the app ignores `season.reset`, leaves the stale route/data in place, and does not remount the draw page.

- [ ] **Step 4: Implement one app-level reset handler**

```tsx
const applySeasonReset = (result?: SeasonResetResult) => {
  const alreadyApplied = Date.now() - lastSeasonResetAt.current < 5_000;
  if (!alreadyApplied) lastSeasonResetAt.current = Date.now();
  setResetNotice(current => result
    ? `시즌 초기화 완료 · ${result.grant.granted_users}명에게 ${result.grant.total_tickets.toLocaleString()}장 지급`
    : alreadyApplied ? current : "새 시즌이 시작되었습니다.");
  if (alreadyApplied) return;
  setInvite(undefined);
  setFeed([]);
  if (location.pathname !== "/") history.replaceState({}, "", "/");
  setPath("/");
  setSeasonEpoch(value => value + 1);
  void refresh();
  void api<{ items: FeedItem[] }>("/api/feed/five-stars").then(data => setFeed(data.items)).catch(() => {});
};
```

Initialize `lastSeasonResetAt` with `useRef(0)`. Handle `message.type === "season.reset"` before trade messages. Pass `applySeasonReset` to `AdminPage`, pass `seasonEpoch` into `Shell`, and assign it as the `key` of Shell's existing `<main className="content">` so the current page remounts without an extra layout wrapper. Add a dismissible global notice inside `Shell`. Calling the callback from an unmounted admin component remains safe because the callback state belongs to `App`.

Extend the App regression with both orderings: WebSocket event then successful POST callback, and callback then WebSocket event. In each case assert exactly one route replacement, one epoch remount/status reload, and one feed reload; the detailed administrator success text must win whenever a result payload is available.

- [ ] **Step 5: Run App tests and the full frontend suite**

Run from `web`:

```powershell
npm test -- src/App.test.tsx
npm test
npm run build
```

Expected: realtime regression tests, all component tests, and production build pass.

- [ ] **Step 6: Commit realtime refresh behavior**

```powershell
git add -- web/src/App.tsx web/src/App.test.tsx web/src/styles.css
git commit -m "feat(cards): refresh clients after season reset"
```

---

### Task 8: End-to-end regression and operations runbook

**Files:**
- Modify: `tests/bandi_cards/test_admin_season_reset.py`
- Modify: `tests/test_card_commands.py`
- Modify: `tests/test_discord_profiles.py`
- Modify: `docs/operations/bandi-card-site.md`

**Interfaces:**
- Consumes: the complete backend and frontend reset flow.
- Produces: deployment-safe verification evidence and an operator checklist that never automatically triggers production reset.

- [ ] **Step 1: Add the post-reset vertical-flow test**

Seed two users, five valid rarity pools, settings with `daily_draws=10` and `new_user_bonus_tickets=20`, progression, history, trade, and audit data. Execute the admin endpoint, then use the same authenticated client to assert:

```python
assert client.get("/api/auth/me").status_code == 200
assert client.get("/api/collection/me").json()["cards"] == []
assert client.get("/api/catalog").json()["owned_count"] == 0
assert client.get("/api/draw/history").json()["total"] == 0
assert client.get("/api/feed/five-stars").json()["items"] == []
assert all(item["total_yp"] == 0 for item in client.get("/api/rankings").json()["items"])
status_payload = client.get("/api/draw/status").json()
assert status_payload["daily_remaining"] == configured_daily_draws
assert status_payload["bonus_tickets"] == configured_new_user_bonus
assert status_payload["four_remaining"] == 10
assert status_payload["five_remaining"] == 90
ten = client.post("/api/draw/ten", headers={"X-CSRF-Token": csrf}, json={"idempotency_key": "post-reset-ten"})
assert ten.status_code == 200
assert len(ten.json()["cards"]) == 10
single = client.post("/api/draw", headers={"X-CSRF-Token": csrf}, json={"idempotency_key": "post-reset-single"})
assert single.status_code == 200
assert client.get("/api/draw/history").json()["total"] == 11
```

After those draws, use the existing `send_gift`, `create_trade`, `accept_invite`, `set_offer`, and `accept_offer` service helpers with the second preserved user to prove newly acquired inventory can again be gifted and traded. Assert no pre-reset `NotificationOutbox.payload` remains and that any resulting outbox row belongs only to the new gift/trade action. Create one new Discord user through the exact OAuth callback stub pattern in `tests/bandi_cards/test_auth_accounts.py`, then assert that user receives 10 immediately available daily draws and the unchanged 20-ticket signup benefit.

Add a bot integration regression to `tests/test_card_commands.py`: seed non-zero inventories, run the reset service and commit, then call `create_ranking_embed(..., session_factory=web_db)` and assert every displayed YP value is zero while the configured `/ranking` link remains present. The existing `/가챠` link and command-registration tests remain unchanged.

Add a profile-sync regression to `tests/test_discord_profiles.py`: keep a stale preserved `User` through `execute_season_reset`, run the existing `sync_profile_batch` fake-client flow, and assert username, global name, avatar, timestamps, and cleared sync error update normally on that same user ID.

- [ ] **Step 2: Run the vertical-flow test and verify it passes**

Run: `python -m pytest tests/bandi_cards/test_admin_season_reset.py tests/test_card_commands.py tests/test_discord_profiles.py -q`

Expected: all reset API and post-reset product flows pass.

- [ ] **Step 3: Document the manual operating sequence**

Add a `시즌 초기화` section to `docs/operations/bandi-card-site.md` with this exact order:

1. Confirm Railway PostgreSQL backup/snapshot availability.
2. Open 관리자 센터 → 위험 구역 → 초기화 대상 확인.
3. Compare preserved card/set/probability/draw-setting counts with expected production configuration.
4. Confirm delete counts and notify active users of the short maintenance window.
5. Type `영호 가챠 시즌 초기화` and execute once.
6. Verify the same administrator session remains logged in.
7. Verify empty inventory/catalog progress/ranking YP/five-star history.
8. Verify configured daily draws and reissued signup-benefit tickets.
9. Perform one controlled draw and confirm a new history row starts the season.
10. Do not run SQL manually or repeat the action to troubleshoot; inspect logs and restore from backup if the transaction reports an unexpected result.

- [ ] **Step 4: Run fresh complete verification**

From the repository root:

```powershell
python -m pytest -q
python -m py_compile bandi_cards/season_reset.py bandi_cards/services/season_reset.py bandi_cards/routes/admin_reset.py
git diff --check
```

From `web`:

```powershell
npm test
npm run build
```

Expected: Python tests report zero failures, frontend tests report zero failures, the production build exits 0, Python compilation exits 0, and `git diff --check` prints no errors.

- [ ] **Step 5: Review the final diff against the preserve/delete matrix**

Confirm the reset code contains no delete statement targeting `users`, `web_sessions`, `oauth_attempts`, `rarity_settings`, `cards`, any set table, `draw_settings`, or `image_cleanup`. Confirm no production Railway command or test calls `POST /api/admin/season-reset`.

- [ ] **Step 6: Commit the runbook and final regression**

```powershell
git add -- tests/bandi_cards/test_admin_season_reset.py tests/test_card_commands.py tests/test_discord_profiles.py docs/operations/bandi-card-site.md
git commit -m "test(cards): verify season reset lifecycle"
```

- [ ] **Step 7: Push and observe deployment without executing reset**

```powershell
git push origin master
railway deployment list --service Youngho-Gatcha --limit 2
railway logs --service Youngho-Gatcha --latest --lines 100
```

Expected: the new deployment reaches `SUCCESS`, `/api/health` remains healthy, and logs contain no startup exception. Verify only the preview endpoint in production; leave the destructive POST for the administrator.
