"""Claude agent loop for Home Assistant control."""

import logging
from typing import Optional

import anthropic

from .config import get_config
from .tools import select_tools_for_message, execute_tool, format_tool_result, resolve_entity
from .ha_cache import get_cache
from .ha_client import get_ha_client
from .aliases import get_alias_manager
from .usage import get_usage_tracker
from .intent_extractor import extract_intent, get_response_template, SIMPLE_INTENTS

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a helpful Home Assistant controller. You help users monitor and control their smart home through natural language commands.

## Your Capabilities
- Check the status of any entity (lights, locks, sensors, switches, climate, etc.)
- Turn devices on/off, lock/unlock doors, adjust climate settings
- Query history and provide summaries
- Trigger automations and scenes
- Learn and remember user's nicknames for entities

## Guidelines
1. When the user refers to a device by a nickname (like "kitchen light" or "front door"), try to resolve it to the actual entity. If you successfully figure out which entity they mean, use the save_entity_alias tool to remember it for next time.

2. Be concise in your responses. After executing a command, confirm what you did briefly.

3. If you're unsure which entity the user means, ask for clarification.

4. For status checks, provide relevant information without overwhelming detail. For sensors, include the value and unit. For binary states, say on/off or locked/unlocked clearly.

5. When checking multiple entities (like "check all locks"), summarize the results clearly.

6. If a command fails, explain what went wrong and suggest alternatives.

7. IMPORTANT: Avoid listing large domains (sensor, binary_sensor, light) - they have hundreds of entities. Use get_entity_state with a specific name instead. Only use get_entities_by_domain for small domains like lock, climate, or cover.

## Entity Information
{entity_summary}

## Known Aliases
{alias_summary}
"""


def build_system_prompt() -> str:
    """Build the system prompt with current context."""
    cache = get_cache()
    alias_manager = get_alias_manager()

    entity_summary = cache.get_entity_summary()
    alias_summary = alias_manager.get_summary()

    return SYSTEM_PROMPT.format(
        entity_summary=entity_summary,
        alias_summary=alias_summary
    )


def _serialize_content(content) -> list:
    """Serialize response content to a JSON-serializable format."""
    result = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                result.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })
    return result


def _clean_history(history: list) -> list:
    """Clean conversation history to ensure valid message format."""
    cleaned = []
    for msg in history:
        if not msg.get("content"):
            continue  # Skip empty content messages

        content = msg["content"]
        # Ensure content is not empty
        if isinstance(content, str) and not content.strip():
            continue
        if isinstance(content, list) and len(content) == 0:
            continue

        cleaned.append(msg)
    return cleaned


async def try_direct_execution(
    user_message: str,
    conversation_history: Optional[list] = None
) -> tuple[Optional[str], Optional[list], int, int]:
    """
    Try to handle a simple command directly without the full agent loop.

    Returns:
        Tuple of (response_text, updated_history, input_tokens, output_tokens)
        If response_text is None, caller should fall back to full agent.
    """
    tracker = get_usage_tracker()

    # Extract intent using lightweight Claude call
    intent_result = await extract_intent(user_message)

    # If needs full agent, return None to trigger fallback
    if intent_result.needs_full_agent:
        logger.info(f"Intent extraction suggests full agent needed")
        return None, None, 0, 0

    cache = get_cache()

    # Claude already resolved to entity_id - just validate it exists
    if intent_result.entity_id:
        entity_info = cache.get_entity(intent_result.entity_id)

        if not entity_info:
            # Entity doesn't exist - fall back to full agent
            logger.info(f"Entity not found in cache: {intent_result.entity_id}")
            return None, None, 0, 0

        resolved_entity = intent_result.entity_id
        entity_name = entity_info.get("friendly_name", resolved_entity)
    else:
        # No entity provided - fall back to full agent for most intents
        resolved_entity = None
        entity_name = None

    # Execute the intent directly
    ha = get_ha_client()
    success = True
    state = None

    try:
        if intent_result.intent == "turn_on":
            await ha.turn_on(resolved_entity)
            logger.info(f"Direct execution: turn_on {resolved_entity}")

        elif intent_result.intent == "turn_off":
            await ha.turn_off(resolved_entity)
            logger.info(f"Direct execution: turn_off {resolved_entity}")

        elif intent_result.intent == "toggle":
            await ha.toggle(resolved_entity)
            logger.info(f"Direct execution: toggle {resolved_entity}")

        elif intent_result.intent == "lock":
            if not resolved_entity.startswith("lock."):
                resolved_entity = f"lock.{resolved_entity.replace('lock.', '')}"
            await ha.lock(resolved_entity)
            logger.info(f"Direct execution: lock {resolved_entity}")

        elif intent_result.intent == "unlock":
            if not resolved_entity.startswith("lock."):
                resolved_entity = f"lock.{resolved_entity.replace('lock.', '')}"
            await ha.unlock(resolved_entity)
            logger.info(f"Direct execution: unlock {resolved_entity}")

        elif intent_result.intent == "get_state":
            state_data = await ha.get_state(resolved_entity)
            state = state_data.get("state", "unknown")
            attrs = state_data.get("attributes", {})
            unit = attrs.get("unit_of_measurement", "")
            if unit:
                state = f"{state} {unit}"
            logger.info(f"Direct execution: get_state {resolved_entity} = {state}")

        elif intent_result.intent == "set_climate":
            # Try to parse temperature from value
            if intent_result.value:
                try:
                    temp = float(intent_result.value.replace("°", "").replace("F", "").replace("C", "").strip())
                    # Find a climate entity if none specified
                    if not resolved_entity:
                        climate_entities = cache.get_entities(domain="climate")
                        if climate_entities:
                            resolved_entity = climate_entities[0].get("entity_id")
                            entity_name = climate_entities[0].get("friendly_name", resolved_entity)
                    if resolved_entity:
                        await ha.set_climate(resolved_entity, temperature=temp)
                        logger.info(f"Direct execution: set_climate {resolved_entity} to {temp}")
                    else:
                        success = False
                except ValueError:
                    success = False
            else:
                success = False

        else:
            # Unknown intent - shouldn't happen but fall back
            return None, None, 0, 0

    except Exception as e:
        logger.error(f"Direct execution failed: {e}")
        success = False

    # Generate response
    response_text = get_response_template(
        intent_result.intent,
        entity_name or "device",
        success,
        state
    )

    # Update conversation history
    messages = _clean_history(list(conversation_history)) if conversation_history else []
    messages.append({"role": "user", "content": user_message})
    messages.append({"role": "assistant", "content": response_text})

    # Use actual token counts from intent extraction
    input_tokens = intent_result.input_tokens
    output_tokens = intent_result.output_tokens

    logger.info(f"Direct execution complete: {intent_result.intent} on {entity_name} ({input_tokens}+{output_tokens} tokens)")
    return response_text, messages, input_tokens, output_tokens


async def run_agent(
    user_message: str,
    conversation_history: Optional[list] = None
) -> tuple[str, list, Optional[str]]:
    """
    Run the agent with a user message and return the response.

    Args:
        user_message: The user's input message
        conversation_history: Previous messages for context

    Returns:
        Tuple of (response_text, updated_conversation_history, warning_message)
    """
    config = get_config()
    client = anthropic.Anthropic(api_key=config.claude.api_key)
    tracker = get_usage_tracker()

    # Check budget before proceeding
    allowed, budget_warning = tracker.check_budget()
    if not allowed:
        return budget_warning, conversation_history or [], None

    # Try direct execution first for simple commands
    direct_response, direct_history, direct_input, direct_output = await try_direct_execution(
        user_message, conversation_history
    )

    if direct_response is not None:
        # Direct execution succeeded - record usage and return
        tracker.record_usage(direct_input, direct_output)
        logger.info(f"Direct execution used: {direct_input}+{direct_output} tokens (saved full agent loop)")
        return direct_response, direct_history, budget_warning

    # Fall back to full agent loop
    logger.info("Using full agent loop")

    # Build messages list - clean history to remove any empty content
    messages = _clean_history(list(conversation_history)) if conversation_history else []
    messages.append({"role": "user", "content": user_message})

    system_prompt = build_system_prompt()
    max_iterations = 10  # Prevent infinite loops
    total_input_tokens = 0
    total_output_tokens = 0

    # Select tools based on user message (dynamic tool selection for token savings)
    selected_tools = select_tools_for_message(user_message)

    for iteration in range(max_iterations):
        logger.debug(f"Agent iteration {iteration + 1}")

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=4096,
            system=system_prompt,
            tools=selected_tools,
            messages=messages
        )

        # Track token usage
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        logger.debug(f"Response stop_reason: {response.stop_reason}, tokens: {response.usage.input_tokens}+{response.usage.output_tokens}")

        # Check if Claude wants to use tools
        if response.stop_reason == "tool_use":
            # Add assistant's response to messages (serialized for JSON compatibility)
            messages.append({
                "role": "assistant",
                "content": _serialize_content(response.content)
            })

            # Execute each tool call
            tool_results = []
            for content_block in response.content:
                if content_block.type == "tool_use":
                    tool_name = content_block.name
                    tool_input = content_block.input
                    tool_use_id = content_block.id

                    logger.info(f"Executing tool: {tool_name} with {tool_input}")

                    result = await execute_tool(tool_name, tool_input)
                    formatted_result = format_tool_result(result)

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": formatted_result
                    })

            # Add tool results to messages
            messages.append({
                "role": "user",
                "content": tool_results
            })

        else:
            # Claude is done - extract final text response
            response_text = ""
            for content_block in response.content:
                if hasattr(content_block, "text"):
                    response_text += content_block.text

            # Ensure response is never empty
            if not response_text.strip():
                response_text = "Done."
                logger.warning("Empty response from Claude, using fallback")

            # Add final response to history
            messages.append({
                "role": "assistant",
                "content": response_text
            })

            # Trim history if needed
            max_history = config.claude.max_history * 2  # *2 for user+assistant pairs
            if len(messages) > max_history:
                messages = messages[-max_history:]

            # Record token usage
            tracker.record_usage(total_input_tokens, total_output_tokens)
            logger.info(f"Request complete: {total_input_tokens} input + {total_output_tokens} output tokens")

            return response_text, messages, budget_warning

    # If we hit max iterations, return what we have
    tracker.record_usage(total_input_tokens, total_output_tokens)
    logger.warning("Agent hit max iterations")
    return "I apologize, but I wasn't able to complete that request. Please try rephrasing or breaking it into smaller steps.", messages, budget_warning


async def run_scheduled_prompt(prompt: str) -> str:
    """
    Run a scheduled prompt without conversation history.
    Returns just the response text.
    """
    response_text, _, _ = await run_agent(prompt, conversation_history=None)
    return response_text
