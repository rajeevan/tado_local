import asyncio
import logging
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode, HVACAction
from homeassistant.const import UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    
    # Safety check: ensure we have a list to iterate over
    if not isinstance(coordinator.data, list):
        _LOGGER.warning(
            "Expected list from coordinator, but got %s. "
            "Entities will be created when data becomes available.",
            type(coordinator.data)
        )
        coordinator.data = []
    
    # Create entities from available data (may be empty if API is unreachable)
    async_add_entities([TadoZoneThermostat(coordinator, zone) for zone in coordinator.data])
    
    # If no entities were created, log a message
    if not coordinator.data:
        _LOGGER.info(
            "No Tado zones found. This may be normal if the API is unreachable. "
            "Entities will be created automatically when data becomes available."
        )

class TadoZoneThermostat(CoordinatorEntity, ClimateEntity):
    def __init__(self, coordinator, zone):
        """Pass the coordinator to the parent class."""
        super().__init__(coordinator)  # This is the "Listener"
        self.coordinator = coordinator
        # Based on openapi.json, we use thermostat_id and name
        self._id = zone.get("thermostat_id") or zone.get("zone_id")
        zone_name = zone.get("name") or zone.get("zone_name")
        self._attr_name = zone_name if zone_name else "Unknown"
        self._attr_unique_id = f"tado_local_therm_{self._id}"
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

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
        """Return current operation mode."""
        if not self.data:
            return HVACMode.OFF
        
        state = self.data.get("state", {})
        mode = state.get("mode", 0)

        if mode == 3:
            return HVACMode.AUTO
        elif mode == 1:
            return HVACMode.HEAT
        else:
            return HVACMode.OFF

    @property
    def hvac_action(self):
        """Return the current running action (Heating vs Idle)."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        
        # Check the API for the actual heating percentage or request
        # In the AmpScm/TadoLocal API, this is usually 'heating_power' or similar
        state = self.data.get("state", {})
        heating_request = state.get("cur_heating", 0)  # Value 0-100
        
        if heating_request > 0:
            return HVACAction.HEATING
        return HVACAction.IDLE

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        zone_id = self.data.get("zone_id")
        
        if hvac_mode == HVACMode.AUTO:
            # Special command for AmpScm/TadoLocal to resume Tado schedule
            url = f"{self.coordinator.base_url}/zones/{zone_id}/set?heating_enabled=true&mode=auto"
        elif hvac_mode == HVACMode.HEAT:
            url = f"{self.coordinator.base_url}/zones/{zone_id}/set?heating_enabled=true"
        else: # HVACMode.OFF
            url = f"{self.coordinator.base_url}/zones/{zone_id}/set?heating_enabled=false"

        async with self.coordinator.session.post(
            url, 
            headers={"Authorization": f"Bearer {self.coordinator.token}"}
        ) as resp:
            if resp.status != 200:
                _LOGGER.error("Failed to set HVAC mode: %s", resp.status)
            else:
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temp = kwargs.get("temperature")
        zone_id = self.data.get("zone_id")
        
        url = f"{self.coordinator.base_url}/zones/{zone_id}/set?temperature={temp}"
        
        async with self.coordinator.session.post(
            url, 
            headers={"Authorization": f"Bearer {self.coordinator.token}"}
        ) as resp:
            if resp.status != 200:
                _LOGGER.error("Failed to set temperature: %s", resp.status)
            else:
                await asyncio.sleep(1)
                await self.coordinator.async_request_refresh()
                self.async_write_ha_state()

    async def async_turn_on(self):
        """Turn the entity on."""
        await self.async_set_hvac_mode(HVACMode.AUTO)

    async def async_turn_off(self):
        """Turn the entity off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def _send_command(self, url):
        headers = {"Authorization": f"Bearer {self.coordinator.token}"}
        async with self.coordinator.session.post(url, headers=headers) as resp:
            if resp.status == 200:
                # # Wait for hardware to process
                await asyncio.sleep(1)
                # # Force the coordinator to fetch the NEW data from the API
                await self.coordinator.async_request_refresh()
                # MANDATORY: Tell HA to re-run the 'hvac_mode' property logic
                self.async_write_ha_state()
            else:
                _LOGGER.error("Failed to send command to %s: Status %s", url, resp.status)