"""Home Assistant metadata caching layer."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from thefuzz import fuzz, process

if TYPE_CHECKING:
    from .ha_client import HomeAssistantClient

logger = logging.getLogger(__name__)


class HACache:
    """
    Caches slow-changing Home Assistant metadata for faster lookups.

    Cached data:
    - Entity registry (entity_id, friendly_name, domain, device_class)
    - Available services per domain
    - Areas and devices (when available)

    NOT cached (always fetched live):
    - Current entity states
    - History data
    """

    def __init__(self, data_dir: str, refresh_hours: int = 6):
        self.data_dir = Path(data_dir)
        self.cache_file = self.data_dir / "ha_cache.json"
        self.refresh_hours = refresh_hours
        self.data: dict = {
            "entities": [],
            "services": {},
            "areas": [],
            "devices": [],
            "last_refresh": None
        }
        self._loaded = False

    def load(self) -> bool:
        """Load cache from file."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self.data = json.load(f)
                self._loaded = True
                logger.info(f"Loaded cache from {self.cache_file}")
                return True
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
        return False

    def save(self):
        """Save cache to file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w") as f:
            json.dump(self.data, f, indent=2, default=str)
        logger.info(f"Saved cache to {self.cache_file}")

    def needs_refresh(self) -> bool:
        """Check if cache needs refreshing."""
        if not self._loaded or not self.data.get("last_refresh"):
            return True

        last_refresh = datetime.fromisoformat(self.data["last_refresh"])
        hours_since = (datetime.now() - last_refresh).total_seconds() / 3600
        return hours_since >= self.refresh_hours

    async def refresh(self, ha_client: "HomeAssistantClient"):
        """Refresh cache from Home Assistant."""
        logger.info("Refreshing Home Assistant cache...")

        try:
            self.data["entities"] = await ha_client.get_entity_registry()
            self.data["services"] = await ha_client.get_services()
            self.data["areas"] = await ha_client.get_areas()
            self.data["devices"] = await ha_client.get_devices()
            self.data["last_refresh"] = datetime.now().isoformat()
            self._loaded = True
            self.save()
            logger.info(f"Cache refreshed: {len(self.data['entities'])} entities")
        except Exception as e:
            logger.error(f"Failed to refresh cache: {e}")
            raise

    def get_entities(self, domain: Optional[str] = None) -> list[dict]:
        """Get cached entities, optionally filtered by domain."""
        entities = self.data.get("entities", [])
        if domain:
            entities = [e for e in entities if e.get("domain") == domain]
        return entities

    def get_entity(self, entity_id: str) -> Optional[dict]:
        """Get a specific entity by ID."""
        for entity in self.data.get("entities", []):
            if entity.get("entity_id") == entity_id:
                return entity
        return None

    def find_entity(self, search: str, threshold: int = 70) -> Optional[str]:
        """
        Fuzzy match entity by friendly name or entity_id.
        Returns entity_id if match found above threshold, None otherwise.
        """
        entities = self.data.get("entities", [])
        if not entities:
            return None

        # Build search candidates: friendly_name -> entity_id mapping
        candidates = {}
        for entity in entities:
            entity_id = entity.get("entity_id", "")
            friendly_name = entity.get("friendly_name", "")

            # Add friendly name as candidate
            if friendly_name:
                candidates[friendly_name.lower()] = entity_id

            # Also add entity_id (without domain prefix) as candidate
            if "." in entity_id:
                short_id = entity_id.split(".", 1)[1].replace("_", " ")
                candidates[short_id] = entity_id

        if not candidates:
            return None

        # Fuzzy match
        result = process.extractOne(
            search.lower(),
            candidates.keys(),
            scorer=fuzz.ratio
        )

        if result and result[1] >= threshold:
            matched_name = result[0]
            entity_id = candidates[matched_name]
            logger.debug(f"Fuzzy matched '{search}' -> '{entity_id}' (score: {result[1]})")
            return entity_id

        return None

    def get_services(self, domain: Optional[str] = None) -> dict:
        """Get available services, optionally for a specific domain."""
        services = self.data.get("services", {})
        if domain:
            return {domain: services.get(domain, [])}
        return services

    def get_domains(self) -> list[str]:
        """Get list of all entity domains."""
        return list(set(e.get("domain") for e in self.data.get("entities", []) if e.get("domain")))

    def get_entity_summary(self) -> str:
        """Get a summary of cached entities for context."""
        entities = self.data.get("entities", [])
        domains = {}
        for entity in entities:
            domain = entity.get("domain", "unknown")
            domains[domain] = domains.get(domain, 0) + 1

        summary_parts = [f"{count} {domain}" for domain, count in sorted(domains.items())]
        return f"Cached entities: {', '.join(summary_parts)}"


# Global cache instance
_cache: Optional[HACache] = None


def get_cache() -> HACache:
    """Get the global cache instance."""
    global _cache
    if _cache is None:
        raise RuntimeError("Cache not initialized. Call init_cache() first.")
    return _cache


def init_cache(data_dir: str, refresh_hours: int = 6) -> HACache:
    """Initialize the global cache."""
    global _cache
    _cache = HACache(data_dir, refresh_hours)
    _cache.load()
    return _cache
