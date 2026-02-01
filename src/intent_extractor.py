"""Lightweight intent extraction for simple commands."""

import json
import logging
import re
from typing import Optional
from dataclasses import dataclass

import anthropic

from .config import get_config
from .ha_cache import get_cache
from .ha_client import get_ha_client
from .aliases import get_alias_manager

logger = logging.getLogger(__name__)


@dataclass
class ExtractedIntent:
    """Result of intent extraction."""
    intent: str  # turn_on, turn_off, toggle, lock, unlock, get_state, set_climate, set_brightness, unknown
    entity_id: Optional[str]  # Actual entity_id from HA (e.g., "light.kitchen")
    confidence: str  # high, medium, low
    value: Optional[str] = None  # For climate: temperature; for brightness: 0-100 percentage
    alias_to_save: Optional[str] = None  # If user wants to save an alias (e.g., "remember this as X")
    response: Optional[str] = None  # Natural language response to send to user
    needs_full_agent: bool = False  # True if this should go to full agent
    input_tokens: int = 0  # Tokens used for extraction
    output_tokens: int = 0


# Intents we can handle directly
SIMPLE_INTENTS = {
    "turn_on", "turn_off", "toggle",
    "lock", "unlock",
    "get_state",
    "set_climate",
    "set_brightness"
}

# Keywords that suggest we need the full agent
COMPLEX_KEYWORDS = [
    "why", "how come", "what if", "explain",
    "history", "when did", "last time",
    "all the", "every", "check all",
    "compare", "difference",
    "help", "what can you",
    "schedule", "automate", "routine",
    "scene", "script",
    # Automation creation triggers
    "automation", "whenever", "automatically",
    "create a rule", "set up a rule", "make it so",
    "when i leave", "when i arrive", "when i get home",
]

INTENT_EXTRACTION_PROMPT = """Extract the intent from this smart home command and write a brief, natural response.

Available entities:
{entity_list}

Respond ONLY with JSON:
{{"intent": "<intent>", "entity_id": "<exact entity_id from list or null>", "confidence": "<high/medium/low>", "value": "<value or null>", "save_alias": "<alias name or null>", "response": "<brief natural response>"}}

Intents: turn_on, turn_off, toggle, lock, unlock, get_state, set_climate, set_brightness, unknown

Rules:
- Pick the entity_id that best matches semantically
- For locks: prefer [locked]/[unlocked] states over [unknown] (stale entities)
- If user says "remember as"/"call this"/"save as", extract alias in "save_alias"
- Write a short, friendly response (1 sentence) confirming the action. Use the device's friendly name.

Response style: Casual and helpful, like a smart assistant. Vary your responses naturally.
- Good: "Kitchen light is on." / "Got it, turned on the kitchen light." / "Living room lamp is off now."
- Avoid: "Done! I have turned on light.kitchen_light." (too robotic, uses entity_id)

Examples:
- "turn on the kitchen light" → {{"intent": "turn_on", "entity_id": "light.kitchen_light", "confidence": "high", "value": null, "save_alias": null, "response": "Kitchen light is on."}}
- "is the front door locked" → {{"intent": "get_state", "entity_id": "lock.front_door", "confidence": "high", "value": null, "save_alias": null, "response": "Let me check the front door..."}}
- "set temp to 72" → {{"intent": "set_climate", "entity_id": "climate.thermostat", "confidence": "high", "value": "72", "save_alias": null, "response": "Setting the thermostat to 72°."}}
- "turn off bedroom lights" → {{"intent": "turn_off", "entity_id": "light.bedroom", "confidence": "high", "value": null, "save_alias": null, "response": "Bedroom lights are off."}}

Command: """


async def get_condensed_entity_list() -> str:
    """Get a condensed entity list from cache for the prompt.

    Includes learned aliases first for better matching, then
    entity list by domain. For lock entities, includes current
    state to help disambiguate between working and stale ones.
    """
    cache = get_cache()
    entities = cache.data.get("entities", [])

    # Start with learned aliases - these take priority
    lines = []
    try:
        alias_manager = get_alias_manager()
        aliases = alias_manager.get_all()
        if aliases:
            # Group aliases by entity to avoid duplicates
            entity_to_aliases: dict[str, list[str]] = {}
            for alias, entity_id in aliases.items():
                if entity_id not in entity_to_aliases:
                    entity_to_aliases[entity_id] = []
                entity_to_aliases[entity_id].append(alias)

            # Format: "alias1, alias2 -> entity_id"
            alias_lines = []
            for entity_id, alias_list in entity_to_aliases.items():
                alias_lines.append(f"{', '.join(alias_list[:3])}: {entity_id}")

            lines.append("KNOWN ALIASES (prefer these):")
            lines.append(", ".join(alias_lines[:20]))  # Limit to 20 entries
            lines.append("")
    except Exception as e:
        logger.debug(f"Could not load aliases: {e}")

    # Group by domain, showing friendly_name → entity_id
    by_domain: dict[str, list[str]] = {}

    # Priority domains to always include
    priority_domains = {"light", "switch", "lock", "sensor", "climate", "cover", "fan"}

    # For lock domain, fetch current states to show which are working
    lock_states = {}
    try:
        ha = get_ha_client()
        lock_entities = [e for e in entities if e.get("entity_id", "").startswith("lock.")]
        for lock in lock_entities:
            entity_id = lock.get("entity_id")
            try:
                state_data = await ha.get_state(entity_id)
                state = state_data.get("state", "unknown")
                lock_states[entity_id] = state
            except Exception:
                lock_states[entity_id] = "unknown"
    except Exception as e:
        logger.warning(f"Could not fetch lock states: {e}")

    for entity in entities:
        entity_id = entity.get("entity_id", "")
        friendly_name = entity.get("friendly_name", "")
        domain = entity_id.split(".")[0] if "." in entity_id else ""

        if not domain:
            continue

        if domain not in by_domain:
            by_domain[domain] = []

        # Format: "friendly_name (entity_id)" or just "entity_id"
        # For locks, include state to help Claude pick working ones
        if domain == "lock" and entity_id in lock_states:
            state = lock_states[entity_id]
            if friendly_name and friendly_name != entity_id:
                by_domain[domain].append(f"{friendly_name} [{state}]: {entity_id}")
            else:
                by_domain[domain].append(f"{entity_id} [{state}]")
        elif friendly_name and friendly_name != entity_id:
            by_domain[domain].append(f"{friendly_name}: {entity_id}")
        else:
            by_domain[domain].append(entity_id)

    # Build condensed list - prioritize important domains
    lines.append("ENTITIES BY DOMAIN:")

    # Priority domains first
    for domain in priority_domains:
        if domain in by_domain:
            items = by_domain[domain][:15]  # Limit per domain
            lines.append(f"{domain}: {', '.join(items)}")

    # Other domains (abbreviated)
    other_domains = [d for d in by_domain if d not in priority_domains]
    for domain in sorted(other_domains)[:5]:  # Limit other domains
        items = by_domain[domain][:5]
        lines.append(f"{domain}: {', '.join(items)}")

    return "\n".join(lines)


def should_use_full_agent(message: str) -> bool:
    """Check if message contains keywords that need the full agent."""
    msg_lower = message.lower()

    # Check for complex keywords
    for keyword in COMPLEX_KEYWORDS:
        if keyword in msg_lower:
            logger.debug(f"Complex keyword detected: '{keyword}'")
            return True

    # Check for questions that need reasoning (but not simple state queries)
    if re.search(r'\b(why|how come|what if)\b', msg_lower):
        return True

    # Multiple entities mentioned (e.g., "turn on kitchen and living room lights")
    # But allow "and remember", "and call this", "and save" for alias saving
    if ' and ' in msg_lower and re.search(r'\b(light|lock|switch|fan)s?\b', msg_lower):
        # Check if it's just an alias-saving phrase
        if not re.search(r'\band\s+(remember|call\s+this|save\s+as|name\s+this)', msg_lower):
            return True

    # Automation creation patterns (e.g., "when the door opens, turn on the light")
    if re.search(r'\bwhen\s+(the|my|a)\s+\w+', msg_lower):
        return True

    return False


async def extract_intent(message: str) -> ExtractedIntent:
    """
    Extract intent from a user message using a lightweight Claude call.

    Returns ExtractedIntent with parsed data, or needs_full_agent=True if complex.
    """
    # First check if this needs full agent based on keywords
    if should_use_full_agent(message):
        logger.info(f"Message needs full agent: '{message[:50]}...'")
        return ExtractedIntent(
            intent="unknown",
            entity_id=None,
            confidence="low",
            needs_full_agent=True
        )

    config = get_config()
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    # Get condensed entity list from cache (includes lock states for disambiguation)
    entity_list = await get_condensed_entity_list()

    # Build prompt with entity list
    prompt = INTENT_EXTRACTION_PROMPT.format(entity_list=entity_list) + message

    try:
        response = client.messages.create(
            model=config.claude.model,
            max_tokens=150,  # Slightly higher to accommodate natural response
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        # Parse response
        response_text = response.content[0].text.strip()
        logger.debug(f"Intent extraction response: {response_text}")

        # Try to parse JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            match = re.search(r'\{[^}]+\}', response_text)
            if match:
                data = json.loads(match.group())
            else:
                logger.warning(f"Could not parse intent response: {response_text}")
                return ExtractedIntent(
                    intent="unknown",
                    entity_id=None,
                    confidence="low",
                    needs_full_agent=True
                )

        intent = data.get("intent", "unknown")
        entity_id = data.get("entity_id")
        confidence = data.get("confidence", "low")
        value = data.get("value")
        save_alias = data.get("save_alias")
        natural_response = data.get("response")

        # Validate entity_id exists in cache if provided
        if entity_id:
            cache = get_cache()
            if not cache.get_entity(entity_id):
                logger.warning(f"Claude returned non-existent entity: {entity_id}")
                # Try to find it anyway - might be a slight mismatch
                # Fall back to full agent if entity doesn't exist
                entity_id = None
                confidence = "low"

        # If intent is unknown or confidence is low, use full agent
        needs_full = intent == "unknown" or confidence == "low"

        # If intent is not in our simple list, use full agent
        if intent not in SIMPLE_INTENTS:
            needs_full = True

        # If we need an entity but don't have one, use full agent
        if intent in {"turn_on", "turn_off", "toggle", "lock", "unlock", "get_state"} and not entity_id:
            needs_full = True

        # Log token usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        alias_log = f", alias={save_alias}" if save_alias else ""
        logger.info(f"Intent extraction: {input_tokens}+{output_tokens} tokens, intent={intent}, entity_id={entity_id}{alias_log}")

        return ExtractedIntent(
            intent=intent,
            entity_id=entity_id,
            confidence=confidence,
            value=value,
            alias_to_save=save_alias,
            response=natural_response,
            needs_full_agent=needs_full,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

    except Exception as e:
        logger.error(f"Intent extraction failed: {e}")
        # Fall back to full agent on error
        return ExtractedIntent(
            intent="unknown",
            entity_id=None,
            confidence="low",
            needs_full_agent=True
        )


def get_response_template(intent: str, entity_name: str, success: bool, state: Optional[str] = None) -> str:
    """Get a response template for direct execution results."""
    if not success:
        return f"Sorry, I couldn't {intent.replace('_', ' ')} {entity_name}. Please try again."

    templates = {
        "turn_on": [
            f"Done! {entity_name} is now on.",
            f"Turned on {entity_name}.",
            f"{entity_name} is on now.",
        ],
        "turn_off": [
            f"Done! {entity_name} is now off.",
            f"Turned off {entity_name}.",
            f"{entity_name} is off now.",
        ],
        "toggle": [
            f"Toggled {entity_name}.",
            f"Done! {entity_name} has been toggled.",
        ],
        "lock": [
            f"Locked {entity_name}.",
            f"Done! {entity_name} is now locked.",
            f"{entity_name} is secured.",
        ],
        "unlock": [
            f"Unlocked {entity_name}.",
            f"Done! {entity_name} is now unlocked.",
        ],
        "get_state": [
            f"{entity_name} is {state}." if state else f"Checked {entity_name}.",
        ],
        "set_climate": [
            f"Climate adjusted for {entity_name}.",
            f"Done! Temperature settings updated.",
        ],
        "set_brightness": [
            f"Set {entity_name} to {state}." if state else f"Adjusted brightness for {entity_name}.",
            f"Done! {entity_name} brightness set to {state}." if state else f"Brightness adjusted.",
        ],
    }

    import random
    options = templates.get(intent, [f"Done! Completed {intent} on {entity_name}."])
    return random.choice(options)
