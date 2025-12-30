import logging
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Safety check: ensure we have a list to iterate over
    if not isinstance(coordinator.data, list):
        _LOGGER.error("Expected list from coordinator, but got %s", type(coordinator.data))
        return

    async_add_entities([TadoZoneThermostat(coordinator, zone) for zone in coordinator.data])

class TadoZoneThermostat(ClimateEntity):
    def __init__(self, coordinator, zone):
        self.coordinator = coordinator
        # Based on openapi.json, we use thermostat_id and name
        self._id = zone.get("thermostat_id") or zone.get("zone_id")
        self._attr_name = zone.get("name") or zone.get("zone_name")
        self._attr_unique_id = f"tado_local_therm_{self._id}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    @property
    def data(self):
        # Safely find the current device data in the coordinator
        if not self.coordinator.data:
            return None
        return next((z for z in self.coordinator.data if (z.get("thermostat_id") == self._id or z.get("zone_id") == self._id)), None)

    @property
    def current_temperature(self):
        state = self.data.get("state", {}) if self.data else {}
        return state.get("cur_temp_c")

    @property
    def target_temperature(self):
        state = self.data.get("state", {}) if self.data else {}
        return state.get("target_temp_c")

    @property
    def hvac_mode(self):
        if not self.data: return HVACMode.OFF
        mode = self.data.get("state", {}).get("mode")
        return HVACMode.HEAT if mode == 1 else HVACMode.OFF

    async def async_set_hvac_mode(self, hvac_mode):
        enabled = "true" if hvac_mode == HVACMode.HEAT else "false"
        # Using the correct endpoint from openapi.json
        url = f"{self.coordinator.base_url}/thermostats/{self._id}/set?heating_enabled={enabled}"
        await self._send_command(url)

    async def async_set_temperature(self, **kwargs):
        temp = kwargs.get("temperature")
        url = f"{self.coordinator.base_url}/thermostats/{self._id}/set?temperature={temp}"
        await self._send_command(url)

    async def _send_command(self, url):
        headers = {"Authorization": f"Bearer {self.coordinator.token}"}
        async with self.coordinator.session.post(url, headers=headers) as resp:
            if resp.status == 200:
                await self.coordinator.async_request_refresh()
            else:
                _LOGGER.error("Failed to send command to %s: Status %s", url, resp.status)