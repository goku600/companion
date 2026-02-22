"""
Atlassian Rovo Dev AI Agent client.

Uses the Atlassian Remote Agent API (Rovo Dev) via HTTPS with
basic-auth (email + API key).

API reference:
  https://developer.atlassian.com/cloud/rovo/rovo-agents/rest/api-group-agent-conversation/
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Maximum characters of file text content to send in a single message
MAX_FILE_TEXT_CHARS = 30_000

# Text-based MIME type prefixes / suffixes we can send as plain text
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


class RovoDevClient:
    """Async client that wraps the Atlassian Rovo Dev Agent REST API."""

    # Rovo Dev agent chat endpoint
    # POST /v1/chat  (per-agent URL differs per site/agent)
    # We use the generic "Rovo Dev" agent endpoint.
    _AGENT_PATH = "/api/v1/agents/rovo-dev/conversations"

    def __init__(self, email: str, api_key: str, site_url: str) -> None:
        self.email = email
        self.api_key = api_key
        # Normalise — strip trailing slash and any /rovodev suffix
        self.site_url = site_url.rstrip("/")
        if self.site_url.endswith("/rovodev"):
            self.site_url = self.site_url[: -len("/rovodev")]

        credentials = f"{email}:{api_key}"
        encoded = base64.b64encode(credentials.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            follow_redirects=True,
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
        history = list(history)  # copy
        history.append({"role": "user", "content": user_message})

        reply = await self._call_agent(history)

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
        Send a message with file content attached.

        For text-based files the raw content is embedded in the prompt.
        For binary files (images, PDFs, etc.) we base64-encode them and
        embed them as a data-URI in the message content so Rovo Dev can
        process them.
        """
        history = list(history)

        # Build the combined message
        combined = self._build_file_message(
            user_message, file_name, file_bytes, mime_type
        )
        history.append({"role": "user", "content": combined})

        reply = await self._call_agent(history)
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

    def _build_file_message(
        self,
        user_message: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
    ) -> str:
        """Build the combined user prompt that includes the file payload."""
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

        if self._is_text_mime(mime_type) or ext in {
            "py", "js", "ts", "java", "c", "cpp", "h", "hpp", "cs", "go",
            "rb", "rs", "swift", "kt", "sh", "bash", "zsh", "fish",
            "yaml", "yml", "toml", "ini", "cfg", "conf",
            "md", "rst", "txt", "log", "csv", "json", "xml", "html", "css",
            "sql", "r", "m", "lua", "pl", "php",
        }:
            # Embed as plain text
            try:
                text_content = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                text_content = file_bytes.decode("latin-1", errors="replace")

            if len(text_content) > MAX_FILE_TEXT_CHARS:
                text_content = (
                    text_content[:MAX_FILE_TEXT_CHARS]
                    + f"\n\n[... truncated — file exceeded {MAX_FILE_TEXT_CHARS} characters ...]"
                )

            return (
                f"{user_message}\n\n"
                f"--- FILE: {file_name} ---\n"
                f"```\n{text_content}\n```"
            )
        else:
            # Embed as base64 data-URI for binary formats (images, PDFs, etc.)
            b64 = base64.b64encode(file_bytes).decode()
            data_uri = f"data:{mime_type};base64,{b64}"
            # Truncate very large binary files to avoid exceeding API limits
            MAX_DATA_URI = 500_000
            if len(data_uri) > MAX_DATA_URI:
                return (
                    f"{user_message}\n\n"
                    f"⚠️ The file <{file_name}> is too large to send in full "
                    f"({len(file_bytes):,} bytes). Please try a smaller file."
                )
            return (
                f"{user_message}\n\n"
                f"The user has attached a file named '{file_name}' "
                f"(MIME type: {mime_type}).\n"
                f"File content (base64 data-URI):\n{data_uri}"
            )

    async def _call_agent(
        self, messages: list[dict[str, Any]]
    ) -> str:
        """
        POST to the Rovo Dev conversation endpoint and return the assistant reply text.

        Atlassian Rovo Dev uses the following endpoint pattern:
          POST https://<site>.atlassian.net/gateway/api/assist/chat/v1/chat
        with body:
          {
            "recipients": [{"type": "agent", "id": "rovo-dev"}],
            "content": [{"type": "text", "text": "..."}]
          }

        We support both the public Atlassian cloud gateway and the
        direct api.atlassian.com endpoint.
        """
        # Determine base URL strategy
        base = self.site_url

        # ---- Strategy 1: Atlassian Assist / Rovo gateway ----
        # https://<your-site>.atlassian.net/gateway/api/assist/chat/v1/chat
        if "atlassian.net" in base:
            url = f"{base}/gateway/api/assist/chat/v1/chat"
            payload = self._build_assist_payload(messages)
        else:
            # ---- Strategy 2: api.atlassian.com remote agent REST API ----
            # https://api.atlassian.com/v1/agents/rovo-dev/conversations
            url = f"{base}{self._AGENT_PATH}"
            payload = self._build_remote_agent_payload(messages)

        logger.debug("POST %s  payload_keys=%s", url, list(payload.keys()))

        response = await self._http.post(url, headers=self._headers, json=payload)

        if response.status_code == 401:
            raise RuntimeError(
                "Authentication failed (401). Check your ATLASSIAN_EMAIL and ATLASSIAN_API_KEY."
            )
        if response.status_code == 403:
            raise RuntimeError(
                "Forbidden (403). Your account may not have access to Rovo Dev. "
                "Ensure Rovo is enabled for your Atlassian site."
            )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"Rovo Dev API returned HTTP {response.status_code}: {response.text[:500]}"
            )

        return self._parse_response(response)

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def _build_assist_payload(self, messages: list[dict]) -> dict:
        """
        Payload for the Atlassian Assist gateway chat endpoint.
        """
        # Convert history to the expected format
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        return {
            "recipients": [{"type": "agent", "id": "rovo-dev"}],
            "messages": formatted_messages,
        }

    def _build_remote_agent_payload(self, messages: list[dict]) -> dict:
        """
        Payload for the Atlassian Remote Agent REST API.
        """
        return {
            "messages": [
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ]
        }

    def _parse_response(self, response: httpx.Response) -> str:
        """Extract the assistant's text reply from the API response."""
        try:
            data = response.json()
        except Exception:
            return response.text.strip()

        # Try common response shapes
        # Shape 1: {"message": {"content": "..."}}
        if "message" in data and isinstance(data["message"], dict):
            return data["message"].get("content", str(data))

        # Shape 2: {"choices": [{"message": {"content": "..."}}]}  (OpenAI-compat)
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            if "message" in choice:
                return choice["message"].get("content", str(choice))
            if "text" in choice:
                return choice["text"]

        # Shape 3: {"content": "..."}
        if "content" in data:
            content = data["content"]
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # ADF-style content blocks
                return self._extract_text_from_adf(content)

        # Shape 4: {"response": "..."}
        if "response" in data:
            return str(data["response"])

        # Shape 5: {"text": "..."}
        if "text" in data:
            return str(data["text"])

        # Fallback
        return json.dumps(data, indent=2)

    def _extract_text_from_adf(self, content_blocks: list) -> str:
        """Recursively extract plain text from ADF content blocks."""
        parts = []
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
            if "content" in block and isinstance(block["content"], list):
                parts.append(self._extract_text_from_adf(block["content"]))
        return "".join(parts)

    async def close(self) -> None:
        await self._http.aclose()
