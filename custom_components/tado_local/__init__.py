import asyncio
import logging
import async_timeout
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
    
    # Store coordinator for platforms (climate.py) to use
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Attempt first refresh with timeout and error handling
    # Don't block startup if API is unreachable
    try:
        async with async_timeout.timeout(10):  # 10 second timeout
            await coordinator.async_config_entry_first_refresh()
            _LOGGER.debug("Tado Local data refreshed successfully")
    except (asyncio.TimeoutError, Exception) as err:
        _LOGGER.warning(
            "Failed to refresh Tado Local data during setup: %s. "
            "Component will continue to retry in the background.",
            err
        )
        # Initialize with empty data so entities can still be created
        coordinator.data = []
    
    # Forward the setup to the climate platform
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    _LOGGER.debug("Tado Local climate platform setup successfully")
    
    # Start SSE connection after setup completes (non-blocking)
    # Per Home Assistant docs: hass.async_create_task ensures the task runs
    # in the event loop without blocking setup
    coordinator._start_sse_after_setup()
    _LOGGER.debug("Tado Local SSE connection scheduled (non-blocking)")
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])
    if unload_ok:
        _LOGGER.debug("Tado Local unload_ok: %s", unload_ok)
        coordinator = hass.data[DOMAIN].get(entry.entry_id)
        if coordinator:
            await coordinator.async_shutdown()
            _LOGGER.debug("Tado Local coordinator shutdown successfully")
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Tado Local entry popped successfully")
    _LOGGER.debug("Tado Local unloaded successfully")
    return unload_ok