import asyncio
import logging
import struct
from io import BytesIO
from typing import Optional, Dict, Tuple
from bleak import BleakClient
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from PIL import Image

from .const import IDM_SERVICE_UUID, IDM_CHAR_WRITE, DISPLAY_WIDTH, DISPLAY_HEIGHT

_LOGGER = logging.getLogger(__name__)

class IdmBleClient:

    def __init__(self, hass: HomeAssistant, mac: str) -> None:
        self._hass = hass
        self._mac = mac
        self._client: Optional[BleakClient] = None
        self._lock = asyncio.Lock()
        self._last_image_bytes: Optional[bytes] = None
        self._init_default_image()

    def _init_default_image(self):
        try:
            img = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), color='black')
            img_byte_arr = BytesIO()
            img.save(img_byte_arr, format='PNG')
            self._last_image_bytes = img_byte_arr.getvalue()
        except Exception as e:
            _LOGGER.warning("Failed to init default image: %s", e)

    def get_last_frame(self) -> bytes | None:
        return self._last_image_bytes

    async def ensure_connected(self) -> None:
        if self._client and self._client.is_connected:
            return

        async with self._lock:
            if self._client and self._client.is_connected:
                return

            device = bluetooth.async_ble_device_from_address(self._hass, self._mac, connectable=True)
            
            if device is None:
                _LOGGER.error("BLE device %s not found.", self._mac)
                raise ConnectionError(f"IDM {self._mac} not available")

            try:
                self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
                await self._client.connect()
                _LOGGER.info("Connected to IDM %s", self._mac)
            except Exception as e:
                _LOGGER.error("Failed to connect: %s", e)
                raise ConnectionError(f"Failed to connect to IDM {self._mac}") from e

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.warning("Disconnected from IDM %s", self._mac)
        self._client = None

    async def write_gatt(self, data: bytes, response: bool = False) -> None:
        await self.ensure_connected()
        try:
            await self._client.write_gatt_char(IDM_CHAR_WRITE, data, response=response)
        except Exception:
            if self._client:
                await self._client.disconnect()
            self._client = None
            raise

    # --- Hardware Control ---
    async def set_state(self, on: bool) -> None:
        val = 1 if on else 0
        # Protokół: 0x06, 0x00, CMD(0x04), 0x00, 0x01, 0x00, VAL
        cmd = bytearray([0x06, 0x00, 0x04, 0x00, 0x01, 0x00, val])
        await self.write_gatt(cmd)

    async def set_brightness(self, brightness: int) -> None:
        level = max(0, min(100, brightness))
        # Protokół: 0x06, 0x00, CMD(0x02), 0x00, 0x20, 0x00, VAL
        cmd = bytearray([0x06, 0x00, 0x02, 0x00, 0x20, 0x00, level])
        await self.write_gatt(cmd)

    async def set_mode(self, mode: int) -> None:
        cmd = bytearray([0x06, 0x00, 0x03, 0x00, 0x01, 0x00, mode])
        await self.write_gatt(cmd)

    async def sync_time(self) -> None:
        now = time.localtime()
        year = now.tm_year - 2000
        cmd = bytearray([0x0C, 0x00, 0x08, 0x00, year, now.tm_mon, now.tm_mday, now.tm_hour, now.tm_min, now.tm_sec, now.tm_wday + 1])
        await self.write_gatt(cmd)

    # --- Image Sending ---
    @staticmethod
    def _create_image_payloads(png_data: bytes) -> bytearray:
        png_chunks = [png_data[i:i + 65535] for i in range(0, len(png_data), 65535)]
        idk = len(png_data) + len(png_chunks) 
        payloads = bytearray()
        for i, chunk in enumerate(png_chunks):
            header = struct.pack('<HHB', idk, 0, 2 if i > 0 else 0)
            png_len = struct.pack('<I', len(png_data)) 
            payload = bytearray(header) + png_len + chunk
            payloads.extend(payload)
        return payloads

    async def send_frame_png(self, img: Image.Image) -> None:
        if img.size != (DISPLAY_WIDTH, DISPLAY_HEIGHT):
            img = img.resize((DISPLAY_WIDTH, DISPLAY_HEIGHT), Image.Resampling.NEAREST)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        img_byte_arr = BytesIO()
        img.save(img_byte_arr, format='PNG')
        png_data = img_byte_arr.getvalue()
        self._last_image_bytes = png_data
        payloads = self._create_image_payloads(png_data)
        chunks = [payloads[i:i + 512] for i in range(0, len(payloads), 512)]
        
        await self.ensure_connected()
        
        init_data = bytearray([10, 0, 5, 1, 0, 0, 0, 0, 0, 0])
        await self._client.write_gatt_char(IDM_CHAR_WRITE, bytes(init_data), response=True)
        await asyncio.sleep(0.05)
        
        for chunk in chunks:
            await self._client.write_gatt_char(IDM_CHAR_WRITE, bytes(chunk), response=False) 

    async def send_frame_dict(self, pixels: Dict[Tuple[int, int], Tuple[int, int, int]]) -> None:
        img = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), color='black')
        for (x, y), color in pixels.items():
            if 0 <= x < DISPLAY_WIDTH and 0 <= y < DISPLAY_HEIGHT:
                img.putpixel((x, y), color)
        await self.send_frame_png(img)

    async def clear(self) -> None:
        img = Image.new('RGB', (DISPLAY_WIDTH, DISPLAY_HEIGHT), color='black')
        await self.send_frame_png(img)
