class AutocompleteCore:
    """Central logic for handling events and suggestions."""

    def __init__(self, llm_client, overlay):
        self.llm_client = llm_client
        self.overlay = overlay

    def on_focus_changed(self, event):
        """Handle focus change events (stub)."""
        pass

    def on_text_changed(self, event):
        """Handle text change events (stub)."""
        pass

    def accept_suggestion(self, suggestion):
        """Accept a suggestion and insert it (stub)."""
        pass
