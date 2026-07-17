"""The iServ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IServClient
from .const import DOMAIN
from .coordinator import IServCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iServ from a config entry.

    Creates the API client, coordinator, triggers first data refresh,
    stores the coordinator in hass.data, and forwards sensor platform setup.

    Args:
        hass: The Home Assistant instance.
        entry: The config entry being set up.

    Returns:
        True if setup was successful.
    """
    # Get credentials from config entry data
    url = entry.data["url"]
    username = entry.data["username"]
    password = entry.data["password"]

    # Create aiohttp session via Home Assistant's session manager
    session = async_get_clientsession(hass)

    # Instantiate the iServ API client
    client = IServClient(session, url, username, password)

    # Create the coordinator
    coordinator = IServCoordinator(hass, client)

    # Trigger the first data refresh
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator in hass.data for access by platform entities
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

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
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
