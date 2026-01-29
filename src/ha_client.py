"""Home Assistant REST API client."""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


class HomeAssistantClient:
    """Async client for Home Assistant REST API."""

    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip("/")
        self.token = token
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.headers)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, endpoint: str) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}/api/{endpoint}"
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _post(self, endpoint: str, data: Optional[dict] = None) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}/api/{endpoint}"
        async with session.post(url, json=data or {}) as resp:
            resp.raise_for_status()
            return await resp.json()

    # --- State Methods ---

    async def get_state(self, entity_id: str) -> dict:
        """Get the current state of a single entity."""
        return await self._get(f"states/{entity_id}")

    async def get_states(self, domain: Optional[str] = None) -> list[dict]:
        """Get all entity states, optionally filtered by domain."""
        states = await self._get("states")
        if domain:
            states = [s for s in states if s["entity_id"].startswith(f"{domain}.")]
        return states

    # --- Service Methods ---

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: Optional[str] = None,
        data: Optional[dict] = None
    ) -> list[dict]:
        """Call a Home Assistant service."""
        payload = data or {}
        if entity_id:
            payload["entity_id"] = entity_id
        return await self._post(f"services/{domain}/{service}", payload)

    async def turn_on(self, entity_id: str, **kwargs) -> list[dict]:
        """Turn on an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_on", entity_id, kwargs or None)

    async def turn_off(self, entity_id: str, **kwargs) -> list[dict]:
        """Turn off an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "turn_off", entity_id, kwargs or None)

    async def toggle(self, entity_id: str) -> list[dict]:
        """Toggle an entity."""
        domain = entity_id.split(".")[0]
        return await self.call_service(domain, "toggle", entity_id)

    async def lock(self, entity_id: str) -> list[dict]:
        """Lock a lock entity."""
        return await self.call_service("lock", "lock", entity_id)

    async def unlock(self, entity_id: str) -> list[dict]:
        """Unlock a lock entity."""
        return await self.call_service("lock", "unlock", entity_id)

    async def set_climate(
        self,
        entity_id: str,
        temperature: Optional[float] = None,
        hvac_mode: Optional[str] = None,
        **kwargs
    ) -> list[dict]:
        """Set climate/thermostat settings."""
        data = kwargs
        if temperature is not None:
            data["temperature"] = temperature
        if hvac_mode is not None:
            data["hvac_mode"] = hvac_mode
        return await self.call_service("climate", "set_temperature", entity_id, data)

    # --- Registry/Metadata Methods ---

    async def get_entity_registry(self) -> list[dict]:
        """Get entity registry (all registered entities with metadata)."""
        try:
            # Use websocket API via REST template endpoint
            # This gets more metadata than just /api/states
            session = await self._get_session()
            url = f"{self.base_url}/api/template"
            # Fallback: just return state entities with available info
            states = await self.get_states()
            return [
                {
                    "entity_id": s["entity_id"],
                    "friendly_name": s.get("attributes", {}).get("friendly_name", s["entity_id"]),
                    "domain": s["entity_id"].split(".")[0],
                    "device_class": s.get("attributes", {}).get("device_class"),
                    "area_id": None  # Not available via REST, would need websocket
                }
                for s in states
            ]
        except Exception as e:
            logger.warning(f"Failed to get entity registry: {e}")
            return []

    async def get_areas(self) -> list[dict]:
        """Get all areas/rooms."""
        try:
            # Areas require websocket API, try config endpoint
            config = await self._get("config")
            # Unfortunately areas aren't in config either
            # Return empty - user can populate manually or we enhance later
            return []
        except Exception as e:
            logger.warning(f"Failed to get areas: {e}")
            return []

    async def get_devices(self) -> list[dict]:
        """Get all devices."""
        try:
            # Devices also require websocket API
            return []
        except Exception as e:
            logger.warning(f"Failed to get devices: {e}")
            return []

    async def get_services(self) -> dict[str, list[str]]:
        """Get available services grouped by domain."""
        services = await self._get("services")
        result = {}
        for domain_services in services:
            domain = domain_services.get("domain")
            if domain:
                result[domain] = list(domain_services.get("services", {}).keys())
        return result

    # --- History Methods ---

    async def get_history(
        self,
        entity_id: str,
        hours: int = 24
    ) -> list[list[dict]]:
        """Get state history for an entity."""
        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        endpoint = f"history/period/{start_time}?filter_entity_id={entity_id}"
        return await self._get(endpoint)

    async def get_logbook(
        self,
        entity_id: Optional[str] = None,
        hours: int = 24
    ) -> list[dict]:
        """Get logbook entries."""
        start_time = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        endpoint = f"logbook/{start_time}"
        if entity_id:
            endpoint += f"?entity={entity_id}"
        return await self._get(endpoint)

    # --- Event Methods ---

    async def fire_event(self, event_type: str, event_data: Optional[dict] = None) -> dict:
        """Fire a custom event."""
        return await self._post(f"events/{event_type}", event_data)

    async def trigger_automation(self, entity_id: str) -> list[dict]:
        """Trigger an automation."""
        return await self.call_service("automation", "trigger", entity_id)

    # --- Utility Methods ---

    async def check_connection(self) -> bool:
        """Check if we can connect to Home Assistant."""
        try:
            await self._get("")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Home Assistant: {e}")
            return False


# Global client instance
_client: Optional[HomeAssistantClient] = None


def get_ha_client() -> HomeAssistantClient:
    """Get the global HA client instance."""
    global _client
    if _client is None:
        raise RuntimeError("HA client not initialized. Call init_ha_client() first.")
    return _client


def init_ha_client(url: str, token: str) -> HomeAssistantClient:
    """Initialize the global HA client."""
    global _client
    _client = HomeAssistantClient(url, token)
    return _client
