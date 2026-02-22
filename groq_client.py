"""
Groq AI client for the Telegram bot.
Supports multi-turn chat and file uploads (text, images, PDFs).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from pathlib import Path

from groq import Groq

logger = logging.getLogger(__name__)

# Best free models on Groq in priority order
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",   # Best overall — 70B, very capable
    "llama-3.1-70b-versatile",   # Fallback 70B
    "llama-3.1-8b-instant",      # Fast, lighter
    "mixtral-8x7b-32768",        # Mixtral fallback
    "gemma2-9b-it",              # Google Gemma fallback
]

# MIME types natively supported as images by the vision model
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

# Vision-capable models
VISION_MODELS = {
    "llama-3.2-90b-vision-preview",
    "llama-3.2-11b-vision-preview",
}


def _pick_model(api_key: str, preferred: str | None) -> str:
    """Pick the best available model from Groq."""
    if preferred and preferred.lower() != "auto":
        logger.info("Using configured Groq model: %s", preferred)
        return preferred

    client = Groq(api_key=api_key)
    try:
        available = {m.id for m in client.models.list().data}
        logger.info("Available Groq models: %s", available)
        for model in PREFERRED_MODELS:
            if model in available:
                logger.info("Selected Groq model: %s", model)
                return model
        # Fallback: just use the first available
        if available:
            chosen = next(iter(available))
            logger.info("Fallback Groq model: %s", chosen)
            return chosen
    except Exception as exc:
        logger.warning("Could not list Groq models: %s", exc)

    return PREFERRED_MODELS[0]


class GroqClient:
    """Async-compatible client wrapping the Groq API."""

    SYSTEM_PROMPT = (
        "You are a helpful, friendly AI assistant. "
        "Answer clearly and concisely. When analysing files, "
        "be thorough and structured in your response."
    )

    def __init__(self, api_key: str, model: str = "auto") -> None:
        self._api_key = api_key
        self._client = Groq(api_key=api_key)
        self._model = _pick_model(api_key, model)
        logger.info("GroqClient initialized with model: %s", self._model)

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

        reply = await asyncio.get_event_loop().run_in_executor(
            None, self._call_groq, history
        )

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
        """Send a message with an attached file."""
        history = list(history)

        # Build content parts
        content = self._build_file_content(
            user_message, file_name, file_bytes, mime_type
        )

        history.append({"role": "user", "content": content})

        reply = await asyncio.get_event_loop().run_in_executor(
            None, self._call_groq, history
        )

        # Store simplified history (text only for subsequent turns)
        history[-1] = {
            "role": "user",
            "content": f"{user_message}\n[File: {file_name}]",
        }
        history.append({"role": "assistant", "content": reply})
        return reply, history

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_file_content(
        self,
        user_message: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
    ) -> list[dict] | str:
        """Build the message content with file embedded."""
        # Images — send as base64 image URL if model supports vision
        if mime_type in IMAGE_MIME_TYPES and self._model in VISION_MODELS:
            b64 = base64.b64encode(file_bytes).decode()
            return [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{b64}"
                    },
                },
                {"type": "text", "text": user_message},
            ]

        # For all other files — embed as text
        ext = Path(file_name).suffix.lower()
        text_extensions = {
            ".txt", ".md", ".py", ".js", ".ts", ".java", ".c", ".cpp",
            ".go", ".rs", ".rb", ".php", ".sh", ".bash", ".zsh",
            ".json", ".yaml", ".yml", ".toml", ".xml", ".csv", ".sql",
            ".html", ".css", ".scss", ".log", ".rst", ".ini", ".cfg",
        }

        if ext in text_extensions or mime_type.startswith("text/"):
            try:
                file_text = file_bytes.decode("utf-8", errors="replace")
                return (
                    f"{user_message}\n\n"
                    f"--- File: {file_name} ---\n"
                    f"```\n{file_text}\n```"
                )
            except Exception:
                pass

        # Images (non-vision model) or binary files — base64 embed
        if mime_type in IMAGE_MIME_TYPES:
            b64 = base64.b64encode(file_bytes).decode()
            return (
                f"{user_message}\n\n"
                f"[Image file: {file_name}]\n"
                f"data:{mime_type};base64,{b64[:500]}... (truncated for non-vision model)\n"
                f"Please note: this model doesn't support images natively. "
                f"Describe what you'd like to know about this image."
            )

        # PDF and other binary — base64 with size limit
        max_bytes = 30_000
        if len(file_bytes) > max_bytes:
            snippet = file_bytes[:max_bytes]
            note = f"\n[File truncated — showing first {max_bytes} bytes]"
        else:
            snippet = file_bytes
            note = ""

        try:
            decoded = snippet.decode("utf-8", errors="replace")
            return (
                f"{user_message}\n\n"
                f"--- File: {file_name} ({mime_type}) ---\n"
                f"{decoded}{note}"
            )
        except Exception:
            b64 = base64.b64encode(snippet).decode()
            return (
                f"{user_message}\n\n"
                f"--- File: {file_name} ({mime_type}, base64) ---\n"
                f"{b64}{note}"
            )

    def _call_groq(self, history: list[dict]) -> str:
        """Make a synchronous call to the Groq API."""
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}] + history

        logger.info("Calling Groq model: %s", self._model)
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=4096,
            temperature=0.7,
        )
        return response.choices[0].message.content
