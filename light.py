
from __future__ import annotations
import logging
import voluptuous as vol
from typing import Any, List, Dict
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from PIL import Image, ImageDraw

from .const import DOMAIN, CONF_MAC_ADDRESS, DISPLAY_WIDTH, DISPLAY_HEIGHT
from .ble_client import IdmBleClient
from .fonts import FONT_3X5_DATA, FONT_5X7_DATA

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    mac = entry.data[CONF_MAC_ADDRESS]
    
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        client = hass.data[DOMAIN][entry.entry_id]["client"]
    else:
        client = IdmBleClient(hass, mac)

    light = IDMDisplayEntity(client, mac, entry.title, hass)
    async_add_entities([light])

    platform = entity_platform.async_get_current_platform()

    # Tylko tekst i pixele, jak prosiłeś
    platform.async_register_entity_service(
        "draw_visuals",
        {
            vol.Required("elements"): list,
            vol.Optional("background", default=[0, 0, 0]): list,
        },
        "async_draw_visuals"
    )
    
    platform.async_register_entity_service("clear_display", {}, "async_clear_display")
    platform.async_register_entity_service("sync_time", {}, "async_sync_time")

class IDMDisplayEntity(LightEntity):
    def __init__(self, client: IdmBleClient, mac: str, name: str, hass: HomeAssistant) -> None:
        self._client = client
        self._mac = mac
        self._attr_name = name
        self._attr_unique_id = mac
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_brightness = 255
        self._attr_rgb_color = (255, 255, 255)
        self._is_on = True

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._is_on = True
        
        # 1. Włączenie sprzętowe
        await self._client.set_state(True)

        # 2. Ustawienie jasności (jeśli podano)
        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            # Home Assistant 0-255 -> Device 0-100
            hw_val = int((self._attr_brightness / 255) * 100)
            await self._client.set_brightness(hw_val)
        
        # 3. Ustawienie koloru (jeśli podano)
        if ATTR_RGB_COLOR in kwargs:
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]
            # Przełącz w tryb Custom (0) aby wyświetlić kolor
            await self._client.set_mode(0)
            
            # Pełne wypełnienie kolorem
            color = tuple(self._attr_rgb_color)
            pixels = {}
            for x in range(DISPLAY_WIDTH):
                for y in range(DISPLAY_HEIGHT):
                    pixels[(x, y)] = color
            await self._client.send_frame_dict(pixels)
        else:
            # Samo włączenie przywraca tryb Custom
            await self._client.set_mode(0)

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._is_on = False
        # Wyłączenie sprzętowe
        await self._client.set_state(False)
        self.async_write_ha_state()

    async def async_clear_display(self, **kwargs: Any) -> None:
        await self._client.set_mode(0)
        await self._client.clear()

    async def async_sync_time(self, **kwargs: Any) -> None:
        await self._client.sync_time()

    async def async_draw_visuals(self, elements: list, background: list) -> None:
        # Jeśli wyłączony, włącz ekran
        if not self._is_on:
            await self._client.set_state(True)
            self._is_on = True
            self.async_write_ha_state()
            
        await self._client.set_mode(0)

        canvas = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), tuple(background))
        draw = ImageDraw.Draw(canvas)

        for el in elements:
            el_type = el.get('type')
            if el_type == 'text':
                await self._draw_text_element(draw, el)
            elif el_type == 'pixels':
                self._draw_pixels_element(draw, el)
            else:
                _LOGGER.warning("Ignored element type: %s", el_type)
        
        await self._client.send_frame_png(canvas)

    def _draw_bitmap_char(self, draw, x, y, char, font_data, w, h, color):
        code = ord(char)
        if code >= len(font_data) // w: return
        offset = code * w
        for col in range(w):
            byte = font_data[offset + col]
            for row in range(8): 
                if row >= h: break
                if (byte >> row) & 1:
                    draw.point((x + col, y + row), fill=color)

    async def _draw_text_element(self, draw: ImageDraw.ImageDraw, el: Dict[str, Any]) -> None:
        content = str(el.get('content', ''))
        x = int(el.get('x', 0))
        y = int(el.get('y', 0))
        color = tuple(el.get('color', [255, 255, 255]))
        font_name = el.get('font', '5x7')
        spacing = int(el.get('spacing', 1))
        
        if font_name == '3x5':
            font_data = FONT_3X5_DATA; char_w = 3; char_h = 5
        else:
            font_data = FONT_5X7_DATA; char_w = 5; char_h = 7
            
        cursor_x = x
        for char in content:
            self._draw_bitmap_char(draw, cursor_x, y, char, font_data, char_w, char_h, color)
            cursor_x += char_w + spacing

    def _draw_pixels_element(self, draw: ImageDraw.ImageDraw, el: Dict[str, Any]) -> None:
        pixels = el.get('pixels', [])
        for p in pixels:
            if isinstance(p, list) and len(p) >= 5:
                x, y, r, g, b = int(p[0]), int(p[1]), int(p[2]), int(p[3]), int(p[4])
                if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
                    draw.point((x, y), fill=(r, g, b))
