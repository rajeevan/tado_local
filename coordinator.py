import logging
from datetime import timedelta
import async_timeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

# 1. Define the logger at the top level
_LOGGER = logging.getLogger(__name__)

class TadoDataCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, session, base_url, token):
        self.base_url = base_url
        self.token = token
        self.session = session
        
        # 2. Crucial: Ensure _LOGGER is passed as the second argument
        super().__init__(
            hass, 
            _LOGGER, 
            name="Tado Local API", 
            update_interval=timedelta(seconds=30)
        )

    async def _async_update_data(self):
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with async_timeout.timeout(10):
                async with self.session.get(f"{self.base_url}/thermostats", headers=headers) as response:
                    if response.status != 200:
                        _LOGGER.error("API returned status %s", response.status)
                        return []
                    
                    data = await response.json()
                    
                    # Fix: If API returns {"thermostats": [...]}, extract the list
                    if isinstance(data, dict):
                        return data.get("thermostats") or data.get("zones") or []
                    
                    return data if isinstance(data, list) else []
        except Exception as err:
            _LOGGER.error("Connection error: %s", err)
            return []