from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, Request, status


RESET_IN_PROGRESS_MESSAGE = "시즌 초기화가 진행 중입니다. 잠시 후 다시 시도해주세요."


class SeasonResetInProgress(RuntimeError):
    """Raised when a card-domain mutation starts during a season reset."""


class SeasonResetAlreadyRunning(RuntimeError):
    """Raised when another season reset already owns the coordinator."""


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
    coordinator: SeasonResetCoordinator = request.app.state.season_reset_coordinator
    try:
        async with coordinator.mutation():
            yield
    except SeasonResetInProgress as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RESET_IN_PROGRESS_MESSAGE,
        ) from exc
