
from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from .const import DOMAIN, CONF_MAC_ADDRESS
from .ble_client import IdmBleClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.CAMERA]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.warning("IDM Display: Starting setup for %s", entry.entry_id)
    hass.data.setdefault(DOMAIN, {})
    mac = entry.data[CONF_MAC_ADDRESS]
    client = IdmBleClient(hass, mac)
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "data": entry.data}
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
