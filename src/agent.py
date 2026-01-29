"""Claude agent loop for Home Assistant control."""

import logging
from typing import Optional

import anthropic

from .config import get_config
from .tools import TOOLS, execute_tool, format_tool_result
from .ha_cache import get_cache
from .aliases import get_alias_manager

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

3. If you're unsure which entity the user means, ask for clarification. You can list available entities in a domain to help them.

4. For status checks, provide relevant information without overwhelming detail. For sensors, include the value and unit. For binary states, say on/off or locked/unlocked clearly.

5. When checking multiple entities (like "check all locks"), summarize the results clearly.

6. If a command fails, explain what went wrong and suggest alternatives.

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


async def run_agent(
    user_message: str,
    conversation_history: Optional[list] = None
) -> tuple[str, list]:
    """
    Run the agent with a user message and return the response.

    Args:
        user_message: The user's input message
        conversation_history: Previous messages for context

    Returns:
        Tuple of (response_text, updated_conversation_history)
    """
    config = get_config()
    client = anthropic.Anthropic(api_key=config.claude.api_key)

    # Build messages list
    messages = list(conversation_history) if conversation_history else []
    messages.append({"role": "user", "content": user_message})

    system_prompt = build_system_prompt()
    max_iterations = 10  # Prevent infinite loops

    for iteration in range(max_iterations):
        logger.debug(f"Agent iteration {iteration + 1}")

        response = client.messages.create(
            model=config.claude.model,
            max_tokens=4096,
            system=system_prompt,
            tools=TOOLS,
            messages=messages
        )

        logger.debug(f"Response stop_reason: {response.stop_reason}")

        # Check if Claude wants to use tools
        if response.stop_reason == "tool_use":
            # Add assistant's response to messages
            messages.append({
                "role": "assistant",
                "content": response.content
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

            # Add final response to history
            messages.append({
                "role": "assistant",
                "content": response_text
            })

            # Trim history if needed
            max_history = config.claude.max_history * 2  # *2 for user+assistant pairs
            if len(messages) > max_history:
                messages = messages[-max_history:]

            return response_text, messages

    # If we hit max iterations, return what we have
    logger.warning("Agent hit max iterations")
    return "I apologize, but I wasn't able to complete that request. Please try rephrasing or breaking it into smaller steps.", messages


async def run_scheduled_prompt(prompt: str) -> str:
    """
    Run a scheduled prompt without conversation history.
    Returns just the response text.
    """
    response_text, _ = await run_agent(prompt, conversation_history=None)
    return response_text
