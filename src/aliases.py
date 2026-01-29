"""Entity alias learning and resolution system."""

import json
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from thefuzz import fuzz, process

if TYPE_CHECKING:
    from .ha_cache import HACache

logger = logging.getLogger(__name__)


class AliasManager:
    """
    Manages user-defined and learned aliases for Home Assistant entities.

    Resolution order:
    1. Exact alias match (instant)
    2. Fuzzy alias match (if confidence > 80%)
    3. Fuzzy friendly_name match from cache (if confidence > 70%)
    4. Return None (let the agent ask for clarification)
    """

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.alias_file = self.data_dir / "aliases.json"
        self.aliases: dict[str, str] = {}  # alias -> entity_id
        self._load()

    def _load(self):
        """Load aliases from file."""
        if self.alias_file.exists():
            try:
                with open(self.alias_file) as f:
                    self.aliases = json.load(f)
                logger.info(f"Loaded {len(self.aliases)} aliases from {self.alias_file}")
            except Exception as e:
                logger.warning(f"Failed to load aliases: {e}")
                self.aliases = {}

    def _save(self):
        """Save aliases to file."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.alias_file, "w") as f:
            json.dump(self.aliases, f, indent=2, sort_keys=True)
        logger.info(f"Saved {len(self.aliases)} aliases to {self.alias_file}")

    def resolve(self, user_term: str, cache: "HACache") -> Optional[str]:
        """
        Resolve a user's natural language term to an entity_id.

        Args:
            user_term: The user's name for an entity (e.g., "foyer light")
            cache: The HA cache for fallback fuzzy matching

        Returns:
            entity_id if found, None otherwise
        """
        normalized = user_term.lower().strip()

        # 1. Exact alias match
        if normalized in self.aliases:
            entity_id = self.aliases[normalized]
            logger.debug(f"Exact alias match: '{user_term}' -> '{entity_id}'")
            return entity_id

        # 2. Fuzzy alias match
        if self.aliases:
            result = process.extractOne(
                normalized,
                self.aliases.keys(),
                scorer=fuzz.ratio
            )
            if result and result[1] >= 80:
                matched_alias = result[0]
                entity_id = self.aliases[matched_alias]
                logger.debug(f"Fuzzy alias match: '{user_term}' -> '{entity_id}' (score: {result[1]})")
                return entity_id

        # 3. Fuzzy match from cache friendly names
        entity_id = cache.find_entity(user_term, threshold=70)
        if entity_id:
            logger.debug(f"Cache fuzzy match: '{user_term}' -> '{entity_id}'")
            return entity_id

        logger.debug(f"No match found for: '{user_term}'")
        return None

    def learn(self, alias: str, entity_id: str) -> bool:
        """
        Save a new alias mapping.

        Args:
            alias: The user's name for the entity
            entity_id: The Home Assistant entity_id

        Returns:
            True if saved, False if already exists with same mapping
        """
        normalized = alias.lower().strip()

        # Check if already exists with same mapping
        if normalized in self.aliases and self.aliases[normalized] == entity_id:
            logger.debug(f"Alias already exists: '{alias}' -> '{entity_id}'")
            return False

        self.aliases[normalized] = entity_id
        self._save()
        logger.info(f"Learned alias: '{alias}' -> '{entity_id}'")
        return True

    def remove(self, alias: str) -> bool:
        """Remove an alias."""
        normalized = alias.lower().strip()
        if normalized in self.aliases:
            del self.aliases[normalized]
            self._save()
            logger.info(f"Removed alias: '{alias}'")
            return True
        return False

    def get_all(self) -> dict[str, str]:
        """Get all aliases."""
        return self.aliases.copy()

    def get_aliases_for_entity(self, entity_id: str) -> list[str]:
        """Get all aliases pointing to a specific entity."""
        return [alias for alias, eid in self.aliases.items() if eid == entity_id]

    def get_summary(self) -> str:
        """Get a summary of known aliases."""
        if not self.aliases:
            return "No entity aliases configured."

        # Group by domain
        by_domain: dict[str, list[str]] = {}
        for alias, entity_id in self.aliases.items():
            domain = entity_id.split(".")[0] if "." in entity_id else "other"
            if domain not in by_domain:
                by_domain[domain] = []
            by_domain[domain].append(f"'{alias}' -> {entity_id}")

        parts = []
        for domain in sorted(by_domain.keys()):
            parts.append(f"{domain}: {len(by_domain[domain])} aliases")

        return f"Known aliases: {', '.join(parts)}"


# Global alias manager instance
_alias_manager: Optional[AliasManager] = None


def get_alias_manager() -> AliasManager:
    """Get the global alias manager instance."""
    global _alias_manager
    if _alias_manager is None:
        raise RuntimeError("Alias manager not initialized. Call init_alias_manager() first.")
    return _alias_manager


def init_alias_manager(data_dir: str) -> AliasManager:
    """Initialize the global alias manager."""
    global _alias_manager
    _alias_manager = AliasManager(data_dir)
    return _alias_manager
