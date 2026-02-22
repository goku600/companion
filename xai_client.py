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
    "grok-2-vision-1212",
    "grok-2-1212",
    "grok-2-mini-1212",
]

VISION_MODELS = {
    "grok-2-vision-1212",
}


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
            logger.info("Available xAI models: %s", sorted(available))
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
        return "grok-2-1212"

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
        """Handle file uploads — images via vision API, text files embedded in prompt."""
        import base64

        # ---- Images: use vision model ----
        if mime_type.startswith("image/"):
            if self._model in VISION_MODELS:
                b64 = base64.b64encode(file_bytes).decode()
                data_uri = f"data:{mime_type};base64,{b64}"

                history = list(history)
                history.append({
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": user_message},
                    ],
                })

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
            else:
                combined = (
                    f"{user_message}\n\n"
                    f"[Image '{file_name}' uploaded but current model '{self._model}' "
                    f"does not support vision. Switch to grok-2-vision-1212.]"
                )
                return await self.chat(combined, history)

        # ---- Text-based files: embed content in prompt ----
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
                f"[Note: File '{file_name}' ({mime_type}) is not supported. "
                f"Please share as text or image.]"
            )

        return await self.chat(combined, history)
