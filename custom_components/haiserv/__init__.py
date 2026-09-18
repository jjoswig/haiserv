"""The iServ integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iServ from a config entry.

    Creates the API client, coordinators, triggers first data refreshes,
    stores the coordinators in hass.data, and forwards sensor platform setup.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.
    """
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from homeassistant.helpers.update_coordinator import UpdateFailed
    from homeassistant.exceptions import ConfigEntryNotReady

    from .api import IServClient
    from .const import DOMAIN
    from .coordinator import IServCoordinator, IServParentLetterCoordinator

    # Get credentials from config entry data
    url = entry.data["url"]
    username = entry.data["username"]
    password = entry.data["password"]

    # Create aiohttp session via Home Assistant's session manager
    session = async_get_clientsession(hass)

    # Instantiate the iServ API client
    client = IServClient(session, url, username, password)

    # Create and refresh the current-week coordinator
    coordinator = IServCoordinator(hass, client)
    await coordinator.async_config_entry_first_refresh()

    # Fetch the following week for a separate overview entity. Keep the
    # current-week entity usable if this optional request is unavailable.
    next_week_coordinator = IServCoordinator(hass, client, week_offset=1)
    try:
        await next_week_coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        next_week_coordinator.data = []

    # Store the coordinators for platform entities
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    hass.data[DOMAIN][f"{entry.entry_id}_next_week"] = next_week_coordinator

    # Set up the Elternbrief coordinator. On failure, the sensor will be
    # unavailable but setup proceeds so timetable entities remain functional.
    parentletter_coordinator = IServParentLetterCoordinator(hass, client)
    try:
        await parentletter_coordinator.async_config_entry_first_refresh()
    except (UpdateFailed, ConfigEntryNotReady):
        parentletter_coordinator.data = []
    hass.data[DOMAIN][f"{entry.entry_id}_parentletter"] = parentletter_coordinator

    # Forward platform setup to the sensor module
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an iServ config entry.

    Unloads sensor platforms and cleans up stored data.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being unloaded.

    Returns:
        True if unloading was successful.
    """
    from .const import DOMAIN

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_next_week", None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_parentletter", None)

    return unload_ok
