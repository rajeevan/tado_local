import logging
import json
import asyncio
import copy
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
        self._sse_task = None
        self._sse_running = False
        
        # 2. Crucial: Ensure _LOGGER is passed as the second argument
        # Increase update_interval since SSE will handle real-time updates
        super().__init__(
            hass, 
            _LOGGER, 
            name="Tado Local API", 
            update_interval=timedelta(seconds=300)  # Fallback polling every 5 minutes
        )

    async def async_config_entry_first_refresh(self):
        """Override to start SSE after first refresh."""
        await super().async_config_entry_first_refresh()
        # Start SSE connection after initial data load
        self._start_sse()

    def _start_sse(self):
        """Start the SSE connection task."""
        if self._sse_task is None or self._sse_task.done():
            self._sse_running = True
            self._sse_task = self.hass.async_create_task(self._sse_loop())

    async def async_shutdown(self):
        """Stop SSE connection on shutdown."""
        self._sse_running = False
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass

    async def _sse_loop(self):
        """Main SSE connection loop with reconnection logic."""
        retry_delay = 5
        max_retry_delay = 60
        
        while self._sse_running:
            try:
                await self._connect_sse()
                # If we exit normally, wait before reconnecting
                retry_delay = 5
            except asyncio.CancelledError:
                _LOGGER.debug("SSE task cancelled")
                break
            except Exception as err:
                _LOGGER.warning("SSE connection error: %s. Retrying in %s seconds", err, retry_delay)
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, max_retry_delay)

    async def _connect_sse(self):
        """Connect to SSE endpoint and process events."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "text/event-stream",
            "Cache-Control": "no-cache"
        }
        
        # Connect to /events endpoint with zone and device types
        url = f"{self.base_url}/events?types=zone,device"
        
        _LOGGER.info("Connecting to SSE endpoint: %s", url)
        
        try:
            async with self.session.get(url, headers=headers, timeout=None) as response:
                if response.status != 200:
                    _LOGGER.error("SSE endpoint returned status %s", response.status)
                    raise Exception(f"SSE endpoint returned status {response.status}")
                
                _LOGGER.info("SSE connection established")
                
                # Process SSE stream line by line
                buffer = ""
                async for chunk in response.content.iter_any():
                    if not self._sse_running:
                        break
                    
                    # Decode chunk and add to buffer
                    try:
                        buffer += chunk.decode('utf-8')
                    except UnicodeDecodeError:
                        _LOGGER.warning("Failed to decode SSE chunk")
                        continue
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        # Skip empty lines and comments
                        if not line or line.startswith(':'):
                            continue
                        
                        # Parse SSE format: "data: {...}"
                        if line.startswith('data: '):
                            data_str = line[6:]  # Remove "data: " prefix
                            try:
                                event_data = json.loads(data_str)
                                await self._process_sse_event(event_data)
                            except json.JSONDecodeError as e:
                                _LOGGER.warning("Failed to parse SSE event: %s", e)
                            except Exception as e:
                                _LOGGER.error("Error processing SSE event: %s", e)
        except asyncio.TimeoutError:
            _LOGGER.warning("SSE connection timeout")
            raise
        except Exception as e:
            _LOGGER.error("SSE connection error: %s", e)
            raise

    async def _process_sse_event(self, event_data):
        """Process an SSE event and update coordinator data."""
        event_type = event_data.get("type")
        
        if event_type == "keepalive":
            # Just a keepalive, no update needed
            return
        
        if event_type not in ["zone", "device"]:
            _LOGGER.debug("Ignoring unknown event type: %s", event_type)
            return
        
        _LOGGER.debug("Processing SSE event: type=%s, data=%s", event_type, event_data)
        
        # Get current data and create a deep copy to avoid modifying the original
        current_data = copy.deepcopy(self.data or [])
        
        if event_type == "zone":
            zone_id = event_data.get("zone_id")
            zone_name = event_data.get("zone_name")
            state = event_data.get("state", {})
            
            # Find and update the zone in our data
            updated = False
            for i, zone in enumerate(current_data):
                if zone.get("zone_id") == zone_id or zone.get("thermostat_id") == zone_id:
                    # Update the zone data
                    current_data[i] = {
                        "zone_id": zone_id,
                        "thermostat_id": zone_id,  # For compatibility
                        "name": zone_name or zone.get("name"),
                        "zone_name": zone_name or zone.get("zone_name"),
                        "state": state
                    }
                    updated = True
                    break
            
            if not updated:
                # Zone not found, add it
                current_data.append({
                    "zone_id": zone_id,
                    "thermostat_id": zone_id,
                    "name": zone_name,
                    "zone_name": zone_name,
                    "state": state
                })
        
        elif event_type == "device":
            device_id = event_data.get("device_id")
            serial = event_data.get("serial")
            zone_name = event_data.get("zone_name")
            state = event_data.get("state", {})
            
            # Find the zone this device belongs to and update it
            # Devices typically belong to zones, so we update the zone state
            for i, zone in enumerate(current_data):
                if zone.get("zone_name") == zone_name or zone.get("name") == zone_name:
                    # Update zone state with device state
                    current_data[i]["state"] = state
                    break
        
        # Update coordinator data and notify listeners (local_push)
        self.async_set_updated_data(current_data)
        _LOGGER.debug("Updated coordinator data from SSE event")

    async def _async_update_data(self):
        """Fallback polling method (used if SSE fails or on initial load)."""
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with async_timeout.timeout(10):
                async with self.session.get(f"{self.base_url}/zones", headers=headers) as response:
                    if response.status != 200:
                        _LOGGER.error("API returned status %s", response.status)
                        return self.data or []
                    
                    data = await response.json()
                    
                    # Fix: If API returns {"zones": [...]}, extract the list
                    if isinstance(data, dict):
                        return data.get("zones") or data.get("thermostats") or []
                    
                    return data if isinstance(data, list) else []
        except Exception as err:
            _LOGGER.error("Connection error: %s", err)
            return self.data or []