"""Lightweight intent extraction for simple commands."""

import json
import logging
import re
from typing import Optional
from dataclasses import dataclass

import anthropic

from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class ExtractedIntent:
    """Result of intent extraction."""
    intent: str  # turn_on, turn_off, toggle, lock, unlock, get_state, set_climate, unknown
    entity: Optional[str]  # Raw entity reference from user
    confidence: str  # high, medium, low
    value: Optional[str] = None  # For climate: temperature or mode
    needs_full_agent: bool = False  # True if this should go to full agent
    input_tokens: int = 0  # Tokens used for extraction
    output_tokens: int = 0


# Intents we can handle directly
SIMPLE_INTENTS = {
    "turn_on", "turn_off", "toggle",
    "lock", "unlock",
    "get_state",
    "set_climate"
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
]

INTENT_EXTRACTION_PROMPT = """Extract the intent and entity from this smart home command.

Respond ONLY with JSON, no other text:
{"intent": "<intent>", "entity": "<entity or null>", "confidence": "<high/medium/low>", "value": "<value or null>"}

Intents: turn_on, turn_off, toggle, lock, unlock, get_state, set_climate, unknown

Examples:
"turn on the kitchen light" → {"intent": "turn_on", "entity": "kitchen light", "confidence": "high", "value": null}
"is the front door locked" → {"intent": "get_state", "entity": "front door", "confidence": "high", "value": null}
"set temp to 72" → {"intent": "set_climate", "entity": null, "confidence": "medium", "value": "72"}
"what's the weather like" → {"intent": "unknown", "entity": null, "confidence": "low", "value": null}

Command: """


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
    if ' and ' in msg_lower and re.search(r'\b(light|lock|switch|fan)s?\b', msg_lower):
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
            entity=None,
            confidence="low",
            needs_full_agent=True
        )

    config = get_config()
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    try:
        response = client.messages.create(
            model=config.claude.model,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": INTENT_EXTRACTION_PROMPT + message
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
                    entity=None,
                    confidence="low",
                    needs_full_agent=True
                )

        intent = data.get("intent", "unknown")
        entity = data.get("entity")
        confidence = data.get("confidence", "low")
        value = data.get("value")

        # If intent is unknown or confidence is low, use full agent
        needs_full = intent == "unknown" or confidence == "low"

        # If intent is not in our simple list, use full agent
        if intent not in SIMPLE_INTENTS:
            needs_full = True

        # Log token usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        logger.info(f"Intent extraction: {input_tokens}+{output_tokens} tokens, intent={intent}, entity={entity}")

        return ExtractedIntent(
            intent=intent,
            entity=entity,
            confidence=confidence,
            value=value,
            needs_full_agent=needs_full,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )

    except Exception as e:
        logger.error(f"Intent extraction failed: {e}")
        # Fall back to full agent on error
        return ExtractedIntent(
            intent="unknown",
            entity=None,
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
    }

    import random
    options = templates.get(intent, [f"Done! Completed {intent} on {entity_name}."])
    return random.choice(options)
