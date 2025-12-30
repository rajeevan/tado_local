import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_URL, CONF_PORT, CONF_TOKEN
from .coordinator import TadoDataCoordinator

_LOGGER = logging.getLogger(__name__)

# This is the function Home Assistant is looking for
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado Local from a config entry."""
    base_url = f"{entry.data[CONF_URL]}:{entry.data[CONF_PORT]}"
    session = async_get_clientsession(hass)
    
    coordinator = TadoDataCoordinator(hass, session, base_url, entry.data[CONF_TOKEN])
    
    # Attempt first refresh
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator for platforms (climate.py) to use
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward the setup to the climate platform
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok