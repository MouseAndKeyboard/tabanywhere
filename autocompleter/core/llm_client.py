"""
llm_client.py

A simple client that sends text to an LLM endpoint and retrieves a suggested completion.
"""

import logging
import requests
from ..config import settings

class LLMClient:
    """Client for obtaining suggestions from a language model service."""

    def __init__(self, endpoint=None, timeout=5):
        """
        :param endpoint: Optional override for the LLM endpoint URL.
        :param timeout: Default timeout (seconds) for the HTTP request.
        """
        # If no endpoint is provided here, fall back to settings
        self.endpoint = endpoint or getattr(settings, "LLM_ENDPOINT", None)
        self.timeout = timeout

    def get_suggestion(self, partial_text, context_info=None):
        """
        Request a suggestion from the LLM based on the current partial text and any extra context.

        :param partial_text: The text user has typed so far.
        :param context_info: Additional strings or metadata (e.g. field label, window title).
        :return: A suggestion string or an empty string on failure.
        """
        # If we have no endpoint configured, fall back to a naive suggestion
        if not self.endpoint:
            logging.warning("No LLM endpoint configured; returning a local stub suggestion.")
            return self._fallback_suggestion(partial_text, context_info)

        try:
            payload = {
                "prompt": partial_text,
                "context": context_info or "",
                # Add any LLM-specific parameters you need below:
                "max_tokens": 25,
                "temperature": 0.7
            }

            response = requests.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()  # Raises an HTTPError if the status is 4xx, 5xx

            data = response.json()
            # You’ll need to adapt this depending on how your LLM API returns suggestions
            suggestion = data.get("completion", "").strip()

            return suggestion
        except (requests.RequestException, ValueError) as e:
            logging.error(f"LLM request failed: {e}")
            return ""

    def _fallback_suggestion(self, partial_text, context_info=None):
        """
        Simple fallback logic when no LLM endpoint is available or configured.
        Replace this with any desired local heuristic.
        """
        if not partial_text:
            return "Start typing..."
        # This trivial example just appends "..." to the user’s text
        return partial_text + "..."
