"""Claude agent loop for Home Assistant control."""

import logging
from typing import Optional

import anthropic

from .config import get_config
from .tools import select_tools_for_message, execute_tool, format_tool_result
from .ha_cache import get_cache
from .aliases import get_alias_manager
from .usage import get_usage_tracker

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
