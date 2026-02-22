"""
OpenRouter AI client for the Telegram bot.
OpenRouter provides access to hundreds of AI models via a single API.
Free models: https://openrouter.ai/models?q=free
"""

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Free models available on OpenRouter (in priority order)
PREFERRED_FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "google/gemma-2-9b-it:free",
    "qwen/qwen-2-7b-instruct:free",
]

SYSTEM_PROMPT = (
    "You are a helpful, friendly, and intelligent AI companion. "
    "You engage in natural conversations, answer questions thoroughly, "
    "analyze files and data when provided, and assist with any task. "
    "Be concise but thorough. Use a warm, conversational tone."
)


class OpenRouterClient:
    """Async client for OpenRouter AI API."""

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self, api_key: str, model: str = "auto") -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=self.BASE_URL,
        )
        if model == "auto":
            self._model = PREFERRED_FREE_MODELS[0]
            logger.info("OpenRouterClient using model: %s", self._model)
        else:
            self._model = model
            logger.info("OpenRouterClient using model: %s", self._model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_message: str,
        history: list[dict],
    ) -> tuple[str, list[dict]]:
        """Send a text message and return (reply, updated_history)."""
        history = list(history)
        history.append({"role": "user", "content": user_message})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        )

        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        return reply, history

    async def chat_with_file(
        self,
        user_message: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
        history: list[dict],
    ) -> tuple[str, list[dict]]:
        """Send a message with a file attachment."""
        history = list(history)

        # Check if it's an image
        if mime_type and mime_type.startswith("image/"):
            b64 = base64.b64encode(file_bytes).decode()
            content = [
                {"type": "text", "text": user_message},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
            ]
            history.append({"role": "user", "content": content})
        else:
            # Try to decode as text
            try:
                text_content = file_bytes.decode("utf-8", errors="replace")
                combined = (
                    f"{user_message}\n\n"
                    f"--- File: {file_name} ---\n"
                    f"{text_content[:12000]}"  # limit to 12k chars
                )
                if len(text_content) > 12000:
                    combined += f"\n\n[... file truncated, {len(text_content)} chars total ...]"
            except Exception:
                combined = (
                    f"{user_message}\n\n"
                    f"[Binary file: {file_name}, {len(file_bytes)} bytes — cannot display content]"
                )
            history.append({"role": "user", "content": combined})

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + history,
        )

        reply = response.choices[0].message.content.strip()
        history.append({"role": "assistant", "content": reply})
        return reply, history
