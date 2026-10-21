"""Small HTTP clients for revising a Markdown document with a saved prompt."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROVIDERS = {
    "OpenAI": "gpt-4.1-mini",
    "Anthropic": "claude-sonnet-4-6",
    "Google Gemini": "gemini-3.8-flash",
}
DEFAULT_OPENAI_KEY_PATH = "/home/cport/Documents/API keys/OpenAI.txt"


def _post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
    request = Request(url, data=json.dumps(payload).encode("utf-8"),
                      headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=180) as response:
            return json.load(response)
    except HTTPError as exc:
        # API error bodies can contain request data; never surface them or the key.
        if exc.code in (401, 403):
            raise RuntimeError("The AI service rejected the API key or access to this model.") from None
        if exc.code == 429:
            raise RuntimeError("The AI service rate limit or quota was reached. Try again later.") from None
        raise RuntimeError(f"The AI service returned HTTP {exc.code}. Check the model and API key.") from None
    except URLError as exc:
        raise RuntimeError(f"Could not reach the AI service: {exc.reason}") from None


def generate_revision(provider: str, model: str, key_path: str, prompt: str, original: str) -> str:
    if provider not in PROVIDERS:
        raise ValueError("Choose a supported AI provider.")
    if not model.strip():
        raise ValueError("Enter a model name.")
    if not prompt.strip():
        raise ValueError("Choose a prompt with instructions.")
    try:
        key = Path(key_path).expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"Could not read the API key file: {exc}") from None
    if not key:
        raise ValueError("The API key file is empty.")

    instructions = ("Revise the supplied Markdown document according to the user's instructions. "
                    "Return only the complete revised document, with no explanation or code fence.\n\n"
                    + prompt)
    if provider == "OpenAI":
        result = _post_json("https://api.openai.com/v1/responses",
                            {"Authorization": f"Bearer {key}"},
                            {"model": model.strip(), "instructions": instructions,
                             "input": original, "store": False})
        if result.get("status") != "completed":
            raise RuntimeError("The AI response was incomplete; no revised file was saved.")
        pieces = [part.get("text", "") for item in result.get("output", [])
                  if item.get("type") == "message" for part in item.get("content", [])
                  if part.get("type") == "output_text"]
    elif provider == "Anthropic":
        result = _post_json("https://api.anthropic.com/v1/messages",
                            {"x-api-key": key, "anthropic-version": "2023-06-01"},
                            {"model": model.strip(), "max_tokens": 16384,
                             "system": instructions,
                             "messages": [{"role": "user", "content": original}]})
        if result.get("stop_reason") == "max_tokens":
            raise RuntimeError("The AI response reached its output limit; no revised file was saved.")
        pieces = [part.get("text", "") for part in result.get("content", [])
                  if part.get("type") == "text"]
    else:
        result = _post_json(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent",
            {"x-goog-api-key": key},
            {"systemInstruction": {"parts": [{"text": instructions}]},
             "contents": [{"role": "user", "parts": [{"text": original}]}]},
        )
        candidates = result.get("candidates", [])
        if candidates and candidates[0].get("finishReason") == "MAX_TOKENS":
            raise RuntimeError("The AI response reached its output limit; no revised file was saved.")
        pieces = [part.get("text", "") for part in candidates[0].get("content", {}).get("parts", [])
                  if "text" in part] if candidates else []

    revised = "".join(pieces)
    if not revised.strip():
        raise RuntimeError("The AI returned no revised document; no file was saved.")
    return revised
