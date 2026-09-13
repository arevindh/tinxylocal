"""Shared command plumbing for Tinxy entities.

The optimistic-update approach here follows the ha-tinxylocal fork by @selvakk2k,
reworked to clear the guess on the coordinator update rather than immediately
after the command, so a slow device cannot briefly flash the old state back.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from tinxy import TinxyCommandSuperseded, TinxyError

_LOGGER = logging.getLogger(__name__)

# The relay flips well before the device updates what /info reports, so give it a
# moment before asking. The UI is already showing the optimistic value by then.
SETTLE_DELAY = 0.5


class TinxyOptimisticMixin:
    """Show the expected state immediately, then defer to what the device reports.

    Without this an entity stays visibly stale for the queue delay plus a poll,
    which reads as a laggy or dropped button press. `_optimistic` holds whatever
    the platform wants to display in the meantime (a bool, a percentage, a lock
    state) and is cleared as soon as real data lands.
    """

    _optimistic: Any = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fresh data from the device always wins over what we guessed."""
        self._optimistic = None
        super()._handle_coordinator_update()

    async def _async_command(
        self, optimistic: Any, send: Coroutine[Any, Any, bool]
    ) -> None:
        """Display `optimistic`, run `send`, then re-sync with the device.

        A failed command raises so Home Assistant surfaces it to the user
        instead of leaving the entity silently snapped back to its old state.
        """
        self._optimistic = optimistic
        self.async_write_ha_state()

        try:
            await send
        except TinxyCommandSuperseded:
            # A newer command for this relay is already queued and carries the
            # state the user actually wants. Leave the optimistic value alone
            # for it to resolve, and say nothing.
            return
        except TinxyError as err:
            self._optimistic = None
            self.async_write_ha_state()
            raise HomeAssistantError(f"{self.name}: {err}") from err

        await asyncio.sleep(SETTLE_DELAY)
        await self.coordinator.async_request_refresh()
