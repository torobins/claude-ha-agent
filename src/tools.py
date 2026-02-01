"""Tool definitions and execution for Claude agent."""

import json
import logging
import re
from typing import Any

from .ha_client import get_ha_client
from .ha_cache import get_cache
from .aliases import get_alias_manager

logger = logging.getLogger(__name__)


# =============================================================================
# Individual Tool Definitions
# =============================================================================

TOOL_GET_ENTITY_STATE = {
    "name": "get_entity_state",
    "description": "Get the current state of a Home Assistant entity. Use this to check if lights are on/off, doors locked/unlocked, sensor values, etc.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The entity ID (e.g., 'light.living_room') or a natural language name"
            }
        },
        "required": ["entity_id"]
    }
}

TOOL_GET_ENTITIES_BY_DOMAIN = {
    "name": "get_entities_by_domain",
    "description": "List entities in a domain (max 25). Use for small domains like lock, climate.",
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "The domain (e.g., 'lock', 'climate', 'light')"
            }
        },
        "required": ["domain"]
    }
}

TOOL_TURN_ON = {
    "name": "turn_on",
    "description": "Turn on a light, switch, or other entity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or name"},
            "brightness": {"type": "integer", "description": "Brightness 0-255 (lights)"},
        },
        "required": ["entity_id"]
    }
}

TOOL_TURN_OFF = {
    "name": "turn_off",
    "description": "Turn off a light, switch, or other entity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or name"}
        },
        "required": ["entity_id"]
    }
}

TOOL_TOGGLE = {
    "name": "toggle",
    "description": "Toggle an entity on/off.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or name"}
        },
        "required": ["entity_id"]
    }
}

TOOL_LOCK = {
    "name": "lock_door",
    "description": "Lock a door lock.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Lock entity ID or name (e.g., 'front door')"}
        },
        "required": ["entity_id"]
    }
}

TOOL_UNLOCK = {
    "name": "unlock_door",
    "description": "Unlock a door lock.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Lock entity ID or name"}
        },
        "required": ["entity_id"]
    }
}

TOOL_SET_CLIMATE = {
    "name": "set_climate",
    "description": "Set thermostat/climate temperature or mode.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Climate entity ID or name"},
            "temperature": {"type": "number", "description": "Target temperature"},
            "hvac_mode": {"type": "string", "description": "Mode: heat, cool, auto, off"}
        },
        "required": ["entity_id"]
    }
}

TOOL_GET_HISTORY = {
    "name": "get_history",
    "description": "Get state history for an entity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Entity ID or name"},
            "hours": {"type": "integer", "description": "Hours of history (default: 24)"}
        },
        "required": ["entity_id"]
    }
}

TOOL_CALL_SERVICE = {
    "name": "call_service",
    "description": "Call any Home Assistant service directly.",
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Service domain"},
            "service": {"type": "string", "description": "Service name"},
            "entity_id": {"type": "string", "description": "Optional entity ID"},
            "data": {"type": "object", "description": "Optional service data"}
        },
        "required": ["domain", "service"]
    }
}

TOOL_TRIGGER_AUTOMATION = {
    "name": "trigger_automation",
    "description": "Trigger a Home Assistant automation or scene.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {"type": "string", "description": "Automation/scene entity ID or name"}
        },
        "required": ["entity_id"]
    }
}

TOOL_SAVE_ALIAS = {
    "name": "save_entity_alias",
    "description": "Remember a nickname for an entity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "alias": {"type": "string", "description": "The nickname"},
            "entity_id": {"type": "string", "description": "The actual entity_id"}
        },
        "required": ["alias", "entity_id"]
    }
}

TOOL_CREATE_AUTOMATION = {
    "name": "create_automation",
    "description": "Create a simple automation rule. Use this when the user wants something to happen automatically when a condition is met (e.g., 'when the door opens, turn on the light').",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable name for the automation (e.g., 'Turn on porch light when front door opens')"
            },
            "trigger_entity": {
                "type": "string",
                "description": "Entity ID that triggers the automation (e.g., 'binary_sensor.front_door', 'sensor.motion')"
            },
            "trigger_state": {
                "type": "string",
                "description": "State that triggers the action (e.g., 'on', 'off', 'open', 'closed', 'home', 'away')"
            },
            "action_entity": {
                "type": "string",
                "description": "Entity ID to control when triggered (e.g., 'light.porch', 'lock.front_door')"
            },
            "action": {
                "type": "string",
                "description": "Action to perform: 'turn_on', 'turn_off', 'toggle', 'lock', 'unlock'"
            }
        },
        "required": ["name", "trigger_entity", "trigger_state", "action_entity", "action"]
    }
}

TOOL_LIST_AUTOMATIONS = {
    "name": "list_automations",
    "description": "List all automations in Home Assistant.",
    "input_schema": {
        "type": "object",
        "properties": {}
    }
}

TOOL_DELETE_AUTOMATION = {
    "name": "delete_automation",
    "description": "Delete an automation by its entity ID.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "The automation entity ID (e.g., 'automation.turn_on_porch_light')"
            }
        },
        "required": ["entity_id"]
    }
}


# =============================================================================
# Tool Groups
# =============================================================================

TOOL_GROUPS = {
    "core": {
        "tools": [TOOL_GET_ENTITY_STATE, TOOL_SAVE_ALIAS],
        "keywords": [],  # Always included
    },
    "control": {
        "tools": [TOOL_TURN_ON, TOOL_TURN_OFF, TOOL_TOGGLE],
        "keywords": [
            # Actions
            "turn", "switch", "toggle", "flip",
            "on", "off",
            "enable", "disable",
            "start", "stop",
            "open", "close",  # for covers/blinds
            # Brightness
            "dim", "bright", "brighten", "brightness", "darker", "lighter",
            # Device types
            "light", "lights", "lamp", "lamps",
            "fan", "fans",
            "plug", "outlet",
            "bulb",
        ],
    },
    "security": {
        "tools": [TOOL_LOCK, TOOL_UNLOCK],
        "keywords": [
            # Actions
            "lock", "unlock", "locked", "unlocked",
            "secure", "secured", "unsecure",
            "bolt", "unbolt",
            # Device types
            "door", "doors",
            "deadbolt",
            "entry",
            # Locations (common door names)
            "front", "back", "rear", "side", "garage",
        ],
    },
    "climate": {
        "tools": [TOOL_SET_CLIMATE],
        "keywords": [
            # Temperature
            "temp", "temperature", "temperatures",
            "degree", "degrees",
            # Actions
            "heat", "heating", "warm", "warmer",
            "cool", "cooling", "cold", "colder",
            "hot", "freeze", "freezing",
            # Device types
            "thermostat", "thermostats",
            "hvac", "ac", "a/c",
            "air", "conditioning",
            "furnace", "heater",
            "climate",
        ],
    },
    "query": {
        "tools": [TOOL_GET_ENTITIES_BY_DOMAIN, TOOL_GET_HISTORY],
        "keywords": [
            # Questions
            "what", "which", "how", "where", "when",
            "is", "are", "was", "were",
            # Actions
            "list", "show", "display", "view",
            "get", "tell", "report", "find",
            "check", "see", "look",
            # Concepts
            "all", "every", "each",
            "status", "state", "states",
            "history", "log", "past", "previous",
            "summary", "overview",
            # Counts
            "how many", "count", "number",
        ],
    },
    "advanced": {
        "tools": [TOOL_CALL_SERVICE, TOOL_TRIGGER_AUTOMATION, TOOL_CREATE_AUTOMATION, TOOL_LIST_AUTOMATIONS, TOOL_DELETE_AUTOMATION],
        "keywords": [
            # Automation
            "automation", "automations",
            "scene", "scenes",
            "script", "scripts",
            "routine", "routines",
            # Automation creation triggers
            "when", "whenever", "if",
            "automatically", "auto",
            "create automation", "make automation",
            "set up", "setup",
            "rule", "rules",
            # Actions
            "run", "trigger", "activate", "execute",
            "fire", "invoke", "start",
            "schedule", "workflow",
            # Service calls
            "service", "notify", "notification",
            "media", "play", "pause", "volume",
        ],
    },
}


def select_tools_for_message(message: str) -> list[dict]:
    """
    Select relevant tools based on message content.
    Returns a list of tool definitions.
    """
    msg_lower = message.lower()
    selected_tools = []
    matched_groups = set()

    # Always include core tools
    selected_tools.extend(TOOL_GROUPS["core"]["tools"])
    matched_groups.add("core")

    # Check each group's keywords
    for group_name, group_data in TOOL_GROUPS.items():
        if group_name == "core":
            continue

        for keyword in group_data["keywords"]:
            # Use word boundary matching for short keywords
            if len(keyword) <= 3:
                pattern = rf'\b{re.escape(keyword)}\b'
                if re.search(pattern, msg_lower):
                    if group_name not in matched_groups:
                        selected_tools.extend(group_data["tools"])
                        matched_groups.add(group_name)
                    break
            elif keyword in msg_lower:
                if group_name not in matched_groups:
                    selected_tools.extend(group_data["tools"])
                    matched_groups.add(group_name)
                break

    # If only core matched, add query tools as fallback (for questions)
    if matched_groups == {"core"}:
        selected_tools.extend(TOOL_GROUPS["query"]["tools"])
        matched_groups.add("query")

    logger.info(f"Selected tool groups: {matched_groups} ({len(selected_tools)} tools)")
    return selected_tools


# Full tool list (for backwards compatibility)
TOOLS = [
    {
        "name": "get_entity_state",
        "description": "Get the current state of a Home Assistant entity. Use this to check if lights are on/off, doors locked/unlocked, sensor values, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID (e.g., 'light.living_room') or a natural language name that will be resolved to an entity"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_entities_by_domain",
        "description": "List entities in a specific domain (max 25 results). Use for small domains like lock, climate. For large domains like sensor/light, prefer get_entity_state with a specific name. Domains: light, switch, lock, sensor, binary_sensor, climate, cover, media_player, automation, script.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain to list (e.g., 'lock', 'climate'). Avoid 'sensor' - too many results."
                }
            },
            "required": ["domain"]
        }
    },
    {
        "name": "turn_on",
        "description": "Turn on a light, switch, or other entity that supports being turned on.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID or natural language name"
                },
                "brightness": {
                    "type": "integer",
                    "description": "Optional brightness level 0-255 for lights"
                },
                "color_temp": {
                    "type": "integer",
                    "description": "Optional color temperature in mireds for lights"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "turn_off",
        "description": "Turn off a light, switch, or other entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID or natural language name"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "toggle",
        "description": "Toggle an entity (if on, turn off; if off, turn on).",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID or natural language name"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "lock_door",
        "description": "Lock a door lock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The lock entity ID or natural language name (e.g., 'front door')"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "unlock_door",
        "description": "Unlock a door lock.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The lock entity ID or natural language name"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "set_climate",
        "description": "Set thermostat/climate settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The climate entity ID or natural language name"
                },
                "temperature": {
                    "type": "number",
                    "description": "Target temperature"
                },
                "hvac_mode": {
                    "type": "string",
                    "description": "HVAC mode: heat, cool, auto, off, etc."
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "get_history",
        "description": "Get state history for an entity over the past N hours.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The entity ID or natural language name"
                },
                "hours": {
                    "type": "integer",
                    "description": "Number of hours of history to retrieve (default: 24)"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "list_areas",
        "description": "List all areas/rooms defined in Home Assistant.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "call_service",
        "description": "Call any Home Assistant service directly. Use this for advanced operations not covered by other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Service domain (e.g., 'light', 'script', 'scene')"
                },
                "service": {
                    "type": "string",
                    "description": "Service name (e.g., 'turn_on', 'activate')"
                },
                "entity_id": {
                    "type": "string",
                    "description": "Optional entity ID or name"
                },
                "data": {
                    "type": "object",
                    "description": "Optional service data"
                }
            },
            "required": ["domain", "service"]
        }
    },
    {
        "name": "trigger_automation",
        "description": "Trigger a Home Assistant automation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The automation entity ID or name"
                }
            },
            "required": ["entity_id"]
        }
    },
    {
        "name": "save_entity_alias",
        "description": "Remember a user's nickname for an entity so you can recognize it next time. Call this when you successfully resolve a user's natural language reference to an entity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alias": {
                    "type": "string",
                    "description": "The user's nickname (e.g., 'foyer light', 'front door')"
                },
                "entity_id": {
                    "type": "string",
                    "description": "The actual Home Assistant entity_id"
                }
            },
            "required": ["alias", "entity_id"]
        }
    },
    {
        "name": "get_known_aliases",
        "description": "List all learned entity aliases/nicknames.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "create_automation",
        "description": "Create a simple automation rule. Use when user wants something to happen automatically (e.g., 'when the door opens, turn on the light', 'automatically lock the door when I leave').",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the automation"
                },
                "trigger_entity": {
                    "type": "string",
                    "description": "Entity that triggers the automation (e.g., binary_sensor, sensor, person)"
                },
                "trigger_state": {
                    "type": "string",
                    "description": "State that triggers (e.g., 'on', 'off', 'open', 'home', 'away')"
                },
                "action_entity": {
                    "type": "string",
                    "description": "Entity to control when triggered"
                },
                "action": {
                    "type": "string",
                    "description": "Action: turn_on, turn_off, toggle, lock, unlock"
                }
            },
            "required": ["name", "trigger_entity", "trigger_state", "action_entity", "action"]
        }
    },
    {
        "name": "list_automations",
        "description": "List all automations in Home Assistant.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "delete_automation",
        "description": "Delete an automation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": "The automation entity ID to delete"
                }
            },
            "required": ["entity_id"]
        }
    }
]


def resolve_entity(entity_ref: str) -> str:
    """
    Resolve an entity reference (could be entity_id or natural language name).
    Returns the actual entity_id.
    """
    cache = get_cache()
    alias_manager = get_alias_manager()

    # If it looks like an entity_id, verify it exists
    if "." in entity_ref and " " not in entity_ref:
        # Check if this entity actually exists in cache
        if cache.get_entity(entity_ref):
            return entity_ref
        # Entity doesn't exist - try fuzzy matching the name part
        logger.warning(f"Entity '{entity_ref}' not found in cache, trying fuzzy match")
        # Extract the name part (after the dot) and try to match
        domain, name = entity_ref.split(".", 1)
        search_term = name.replace("_", " ")
        # Try alias resolution first
        resolved = alias_manager.resolve(search_term, cache)
        if resolved:
            logger.info(f"Fuzzy resolved '{entity_ref}' -> '{resolved}'")
            return resolved
        # Try cache fuzzy match
        resolved = cache.find_entity(search_term)
        if resolved:
            logger.info(f"Cache fuzzy matched '{entity_ref}' -> '{resolved}'")
            return resolved

    # Try to resolve via aliases and cache
    resolved = alias_manager.resolve(entity_ref, cache)
    if resolved:
        return resolved

    # Fallback: return as-is and let HA error
    logger.warning(f"Could not resolve entity: '{entity_ref}'")
    return entity_ref


async def execute_tool(name: str, arguments: dict) -> Any:
    """Execute a tool and return the result."""
    ha = get_ha_client()
    cache = get_cache()
    alias_manager = get_alias_manager()

    try:
        if name == "get_entity_state":
            entity_id = resolve_entity(arguments["entity_id"])
            state = await ha.get_state(entity_id)
            return {
                "entity_id": state["entity_id"],
                "state": state["state"],
                "friendly_name": state.get("attributes", {}).get("friendly_name"),
                "attributes": state.get("attributes", {})
            }

        elif name == "get_entities_by_domain":
            domain = arguments["domain"]
            states = await ha.get_states(domain)
            total_count = len(states)
            # Limit to 25 results to avoid token bloat
            limited_states = states[:25]
            result = {
                "domain": domain,
                "total_count": total_count,
                "showing": len(limited_states),
                "entities": [
                    {
                        "entity_id": s["entity_id"],
                        "state": s["state"],
                        "friendly_name": s.get("attributes", {}).get("friendly_name")
                    }
                    for s in limited_states
                ]
            }
            if total_count > 25:
                result["note"] = f"Showing first 25 of {total_count}. Use get_entity_state with a specific name for others."
            return result

        elif name == "turn_on":
            entity_id = resolve_entity(arguments["entity_id"])
            kwargs = {}
            if "brightness" in arguments:
                kwargs["brightness"] = arguments["brightness"]
            if "color_temp" in arguments:
                kwargs["color_temp"] = arguments["color_temp"]
            await ha.turn_on(entity_id, **kwargs)
            return {"success": True, "action": "turned on", "entity_id": entity_id}

        elif name == "turn_off":
            entity_id = resolve_entity(arguments["entity_id"])
            await ha.turn_off(entity_id)
            return {"success": True, "action": "turned off", "entity_id": entity_id}

        elif name == "toggle":
            entity_id = resolve_entity(arguments["entity_id"])
            await ha.toggle(entity_id)
            return {"success": True, "action": "toggled", "entity_id": entity_id}

        elif name == "lock_door":
            entity_id = resolve_entity(arguments["entity_id"])
            if not entity_id.startswith("lock."):
                entity_id = f"lock.{entity_id.replace('lock.', '')}"
            await ha.lock(entity_id)
            return {"success": True, "action": "locked", "entity_id": entity_id}

        elif name == "unlock_door":
            entity_id = resolve_entity(arguments["entity_id"])
            if not entity_id.startswith("lock."):
                entity_id = f"lock.{entity_id.replace('lock.', '')}"
            await ha.unlock(entity_id)
            return {"success": True, "action": "unlocked", "entity_id": entity_id}

        elif name == "set_climate":
            entity_id = resolve_entity(arguments["entity_id"])
            temp = arguments.get("temperature")
            mode = arguments.get("hvac_mode")
            await ha.set_climate(entity_id, temperature=temp, hvac_mode=mode)
            return {"success": True, "action": "climate set", "entity_id": entity_id}

        elif name == "get_history":
            entity_id = resolve_entity(arguments["entity_id"])
            hours = arguments.get("hours", 24)
            history = await ha.get_history(entity_id, hours=hours)
            # Summarize history
            if history and len(history) > 0:
                states = history[0]
                return {
                    "entity_id": entity_id,
                    "hours": hours,
                    "state_changes": len(states),
                    "recent_states": [
                        {"state": s["state"], "last_changed": s.get("last_changed")}
                        for s in states[-10:]  # Last 10 state changes
                    ]
                }
            return {"entity_id": entity_id, "hours": hours, "state_changes": 0}

        elif name == "list_areas":
            areas = cache.data.get("areas", [])
            if not areas:
                return {"areas": [], "note": "Area data not available via REST API"}
            return {"areas": areas}

        elif name == "call_service":
            domain = arguments["domain"]
            service = arguments["service"]
            entity_id = arguments.get("entity_id")
            if entity_id:
                entity_id = resolve_entity(entity_id)
            data = arguments.get("data", {})
            result = await ha.call_service(domain, service, entity_id, data)
            return {"success": True, "domain": domain, "service": service}

        elif name == "trigger_automation":
            entity_id = resolve_entity(arguments["entity_id"])
            if not entity_id.startswith("automation."):
                entity_id = f"automation.{entity_id}"
            await ha.trigger_automation(entity_id)
            return {"success": True, "action": "triggered", "entity_id": entity_id}

        elif name == "save_entity_alias":
            alias = arguments["alias"]
            entity_id = arguments["entity_id"]
            saved = alias_manager.learn(alias, entity_id)
            if saved:
                return {"success": True, "alias": alias, "entity_id": entity_id, "message": f"I'll remember that '{alias}' refers to {entity_id}"}
            return {"success": True, "alias": alias, "entity_id": entity_id, "message": "Alias already known"}

        elif name == "get_known_aliases":
            aliases = alias_manager.get_all()
            return {"aliases": aliases, "count": len(aliases)}

        elif name == "create_automation":
            import uuid
            # Generate a unique ID for the automation
            auto_id = f"claude_{uuid.uuid4().hex[:8]}"

            # Resolve entities
            trigger_entity = resolve_entity(arguments["trigger_entity"])
            action_entity = resolve_entity(arguments["action_entity"])

            # Map action to service
            action = arguments["action"].lower()
            action_map = {
                "turn_on": "turn_on",
                "turn_off": "turn_off",
                "toggle": "toggle",
                "lock": "lock",
                "unlock": "unlock",
            }
            service_action = action_map.get(action, action)

            # Determine the service domain from action entity
            action_domain = action_entity.split(".")[0]
            action_service = f"{action_domain}.{service_action}"

            result = await ha.create_automation(
                automation_id=auto_id,
                alias=arguments["name"],
                trigger_entity=trigger_entity,
                trigger_state=arguments["trigger_state"],
                action_entity=action_entity,
                action_service=action_service
            )
            return {
                "success": True,
                "automation_id": auto_id,
                "name": arguments["name"],
                "message": f"Created automation: {arguments['name']}. It will {service_action} {action_entity} when {trigger_entity} becomes {arguments['trigger_state']}."
            }

        elif name == "list_automations":
            automations = await ha.get_automations()
            return {
                "count": len(automations),
                "automations": automations[:25]  # Limit to 25
            }

        elif name == "delete_automation":
            entity_id = arguments["entity_id"]
            # Extract automation ID from entity_id (e.g., automation.claude_abc123 -> claude_abc123)
            if entity_id.startswith("automation."):
                auto_id = entity_id.replace("automation.", "")
            else:
                auto_id = entity_id
            result = await ha.delete_automation(auto_id)
            return {"success": True, "deleted": entity_id}

        else:
            return {"error": f"Unknown tool: {name}"}

    except Exception as e:
        logger.error(f"Tool execution error ({name}): {e}")
        return {"error": str(e)}


def format_tool_result(result: Any) -> str:
    """Format tool result for Claude."""
    if isinstance(result, dict) or isinstance(result, list):
        return json.dumps(result, indent=2, default=str)
    return str(result)
