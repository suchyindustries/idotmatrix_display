from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from .const import DOMAIN, CONF_MAC_ADDRESS

class IDMDisplayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> FlowResult:
        
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        return await self.async_step_user({CONF_MAC_ADDRESS: discovery_info.address})

    async def async_step_user(self, user_input=None) -> FlowResult:
        
        errors: dict[str, str] = {}
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({
                    vol.Required(CONF_MAC_ADDRESS): str,
                }),
                errors=errors,
            )
        mac = user_input[CONF_MAC_ADDRESS].upper()
        await self.async_set_unique_id(mac)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"IDM Display ({mac})",
            data={CONF_MAC_ADDRESS: mac}
        )
