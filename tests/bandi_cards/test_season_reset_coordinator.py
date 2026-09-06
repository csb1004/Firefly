import asyncio

import pytest
from fastapi import HTTPException

from bandi_cards.season_reset import (
    RESET_IN_PROGRESS_MESSAGE,
    SeasonResetAlreadyRunning,
    SeasonResetCoordinator,
    SeasonResetInProgress,
    track_season_mutation,
)


def test_reset_drains_active_mutation_and_rejects_new_mutation():
    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        mutation_entered = asyncio.Event()
        release_mutation = asyncio.Event()
        reset_entered = asyncio.Event()

        async def mutation() -> None:
            async with coordinator.mutation():
                mutation_entered.set()
                await release_mutation.wait()

        async def reset() -> None:
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
    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        async with coordinator.reset():
            with pytest.raises(SeasonResetAlreadyRunning):
                async with coordinator.reset():
                    pass

        with pytest.raises(RuntimeError, match="injected"):
            async with coordinator.reset():
                raise RuntimeError("injected")

        assert coordinator.is_resetting is False
        async with coordinator.mutation():
            pass

    asyncio.run(scenario())


def test_cancelled_reset_wait_releases_maintenance_state():
    async def scenario() -> None:
        coordinator = SeasonResetCoordinator()
        mutation_entered = asyncio.Event()
        release_mutation = asyncio.Event()

        async def mutation() -> None:
            async with coordinator.mutation():
                mutation_entered.set()
                await release_mutation.wait()

        async def enter_reset() -> None:
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


def test_http_dependency_maps_maintenance_to_503():
    class AppState:
        season_reset_coordinator = SeasonResetCoordinator()

    class App:
        state = AppState()

    class Request:
        app = App()

    async def scenario() -> None:
        coordinator = Request.app.state.season_reset_coordinator
        async with coordinator.reset():
            dependency = track_season_mutation(Request())
            with pytest.raises(HTTPException) as caught:
                await anext(dependency)
            assert caught.value.status_code == 503
            assert caught.value.detail == RESET_IN_PROGRESS_MESSAGE

    asyncio.run(scenario())
