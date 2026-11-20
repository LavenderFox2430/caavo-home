"""Common availability, identifiers, and command handling."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import CaavoAuthError, CaavoError
from .coordinator import CaavoCoordinator, device_info


class CaavoEntity(CoordinatorEntity[CaavoCoordinator]):
    """An entity attached to the stable unit identity, never its IP address."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CaavoCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.client.device_id}_{key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        state = self.coordinator.data or {}
        return (
            super().available
            and state.get("available") is True
            and state.get("branchDisabled") is True
        )

    async def async_command(
        self,
        operation: Callable[..., Awaitable[dict[str, Any]]],
        *args: Any,
        refresh: bool = True,
    ) -> None:
        try:
            await operation(*args)
        except CaavoAuthError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "Caavo rejected its API key; reauthenticate the integration"
            ) from err
        except (CaavoError, ValueError) as err:
            message = str(err)
            if isinstance(err, CaavoError) and err.uncertain:
                message += ". The action may have completed; check the unit before repeating it."
            raise HomeAssistantError(message) from err
        if refresh:
            await self.coordinator.async_request_refresh()


class CaavoAutomationEntity(CaavoEntity):
    """Automation state can fail independently of the normal remote."""

    @property
    def automation(self):
        return (self.coordinator.data or {}).get("automation", {})

    @property
    def available(self):
        return (
            super().available and (self.coordinator.data or {}).get("automationAvailable") is True
        )

    @property
    def can_run(self):
        return (
            self.available
            and not self.automation.get("busy")
            and not self.automation.get("learning")
        )
