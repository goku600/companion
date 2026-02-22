"""
Google Gemini AI client for the Telegram bot.

Supports:
- Multi-turn text conversation with history
- File uploads (text, code, images, PDFs, etc.)
- Uses google-generativeai SDK
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from typing import Any

import google.generativeai as genai

logger = logging.getLogger(__name__)

# Maximum characters of text file content to send in a single message
MAX_FILE_TEXT_CHARS = 30_000

# Text-based MIME type prefixes we can send as plain text
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_TYPES = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/typescript",
    "application/x-python",
    "application/x-sh",
    "application/x-yaml",
    "application/toml",
    "application/csv",
    "application/x-ndjson",
}

# Image MIME types supported natively by Gemini
IMAGE_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "image/heic", "image/heif",
}

# Document MIME types supported natively by Gemini
DOCUMENT_MIME_TYPES = {
    "application/pdf",
}


class GeminiClient:
    """Async-compatible client wrapping the Google Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        genai.configure(api_key=api_key)
        self._model_name = model
        self._model = genai.GenerativeModel(
            model_name=model,
            system_instruction=(
                "You are a helpful, friendly AI assistant. "
                "Answer clearly and concisely. When analysing files, "
                "be thorough and structured in your response."
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(
        self,
        user_message: str,
        history: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Send a text message and return (assistant_reply, updated_history).
        History is a list of {"role": "user"|"assistant", "content": str} dicts.
        """
        history = list(history)

        # Build Gemini-format history (all messages except the current one)
        gemini_history = self._to_gemini_history(history)

        # Start chat session with history
        chat_session = self._model.start_chat(history=gemini_history)

        # Send the new message
        response = chat_session.send_message(user_message)
        reply = response.text.strip()

        # Update history
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply})

        return reply, history

    async def chat_with_file(
        self,
        user_message: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
        history: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Send a message with a file attached.
        - Text/code files: embedded as plain text in the prompt
        - Images: sent natively as inline image parts
        - PDFs: sent natively as inline PDF parts
        - Other binary: base64 encoded and described
        """
        history = list(history)

        # Build the message parts
        parts = self._build_parts(user_message, file_name, file_bytes, mime_type)

        # Build Gemini-format history
        gemini_history = self._to_gemini_history(history)
        chat_session = self._model.start_chat(history=gemini_history)

        response = chat_session.send_message(parts)
        reply = response.text.strip()

        # Store a text summary in history (Gemini parts can't be serialized easily)
        history.append({
            "role": "user",
            "content": f"[Uploaded file: {file_name}] {user_message}"
        })
        history.append({"role": "assistant", "content": reply})

        return reply, history

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_text_mime(self, mime_type: str) -> bool:
        """Return True if the MIME type is textual."""
        if not mime_type:
            return False
        for prefix in TEXT_MIME_PREFIXES:
            if mime_type.startswith(prefix):
                return True
        return mime_type in TEXT_MIME_TYPES

    def _build_parts(
        self,
        user_message: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
    ) -> list:
        """Build Gemini message parts for a file upload."""
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

        # ---- Text / code files ----
        if self._is_text_mime(mime_type) or ext in {
            "py", "js", "ts", "java", "c", "cpp", "h", "hpp", "cs", "go",
            "rb", "rs", "swift", "kt", "sh", "bash", "zsh", "fish",
            "yaml", "yml", "toml", "ini", "cfg", "conf",
            "md", "rst", "txt", "log", "csv", "json", "xml", "html", "css",
            "sql", "r", "m", "lua", "pl", "php",
        }:
            try:
                text_content = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                text_content = file_bytes.decode("latin-1", errors="replace")

            if len(text_content) > MAX_FILE_TEXT_CHARS:
                text_content = (
                    text_content[:MAX_FILE_TEXT_CHARS]
                    + f"\n\n[... truncated — exceeded {MAX_FILE_TEXT_CHARS} chars ...]"
                )

            prompt = (
                f"{user_message}\n\n"
                f"--- FILE: {file_name} ---\n"
                f"```\n{text_content}\n```"
            )
            return [prompt]

        # ---- Images — send natively ----
        if mime_type in IMAGE_MIME_TYPES:
            return [
                user_message or f"Please analyse this image: {file_name}",
                {"mime_type": mime_type, "data": file_bytes},
            ]

        # ---- PDFs — send natively ----
        if mime_type in DOCUMENT_MIME_TYPES:
            return [
                user_message or f"Please analyse this document: {file_name}",
                {"mime_type": mime_type, "data": file_bytes},
            ]

        # ---- Other binary — base64 describe ----
        b64 = base64.b64encode(file_bytes).decode()
        if len(b64) > 500_000:
            return [
                f"{user_message}\n\n"
                f"⚠️ The file '{file_name}' is too large to send "
                f"({len(file_bytes):,} bytes). Please try a smaller file."
            ]
        return [
            f"{user_message}\n\n"
            f"The user attached a file named '{file_name}' "
            f"(MIME type: {mime_type}).\n"
            f"File content (base64):\n{b64}"
        ]

    def _to_gemini_history(self, history: list[dict[str, Any]]) -> list[dict]:
        """Convert internal history format to Gemini SDK format."""
        gemini_history = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            gemini_history.append({
                "role": role,
                "parts": [msg["content"]],
            })
        return gemini_history
