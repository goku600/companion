"""
xAI (Grok) API client for the Telegram companion bot.
"""

import logging
import asyncio
from openai import OpenAI  # xAI is OpenAI-compatible

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a friendly, warm, and supportive AI companion. "
    "You engage in natural, empathetic conversations. "
    "You remember the context of the conversation and respond thoughtfully. "
    "Be concise but meaningful in your responses."
)

PREFERRED_MODELS = [
    "grok-2",
    "grok-2-latest",
    "grok-1",
]


class XAIClient:
    """Client for xAI Grok API (OpenAI-compatible)."""

    def __init__(self, api_key: str, model: str = "auto") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        if model == "auto":
            self._model = self._pick_best_model()
        else:
            self._model = model
        logger.info("XAIClient initialized with model: %s", self._model)

    def _pick_best_model(self) -> str:
        """Pick the best available Grok model."""
        try:
            available = {m.id for m in self._client.models.list().data}
            logger.info("Available xAI models: %s", available)
            for model in PREFERRED_MODELS:
                if model in available:
                    logger.info("Selected xAI model: %s", model)
                    return model
            # Fallback to first available
            if available:
                chosen = sorted(available)[0]
                logger.info("Fallback xAI model: %s", chosen)
                return chosen
        except Exception as exc:
            logger.warning("Could not list xAI models: %s", exc)
        return "grok-2"

    async def chat(
        self,
        user_message: str,
        history: list[dict],
    ) -> tuple[str, list[dict]]:
        """Send a text message and return (reply, updated_history)."""
        history = list(history)
        history.append({"role": "user", "content": user_message})

        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history

        def _call():
            return self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.7,
            )

        response = await asyncio.get_event_loop().run_in_executor(None, _call)
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
        """Handle file uploads — embed text files in the prompt."""
        # For text-based files, embed content directly
        if mime_type.startswith("text/") or any(
            file_name.endswith(ext)
            for ext in (
                ".txt", ".py", ".js", ".ts", ".java", ".c", ".cpp",
                ".go", ".rs", ".rb", ".php", ".sh", ".md", ".rst",
                ".csv", ".json", ".xml", ".yaml", ".toml", ".sql",
                ".html", ".css", ".log",
            )
        ):
            try:
                text_content = file_bytes.decode("utf-8", errors="replace")
                combined = (
                    f"{user_message}\n\n"
                    f"**File: {file_name}**\n"
                    f"```\n{text_content[:12000]}\n```"
                )
            except Exception:
                combined = f"{user_message}\n\n[Could not decode file: {file_name}]"
        else:
            combined = (
                f"{user_message}\n\n"
                f"[Note: File '{file_name}' ({mime_type}) was uploaded but "
                f"xAI Grok currently only supports text content. "
                f"Please share the content as text instead.]"
            )

        return await self.chat(combined, history)
