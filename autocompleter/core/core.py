import time
import threading
import traceback

from ..config import settings

class AutocompleteCore:
    """
    The main, platform-agnostic logic for handling focus changes, text edits,
    LLM queries, and overlay display. The OS-specific hooking layer (e.g. hooking_linux.py)
    should call `on_focus_event(...)` and `on_text_changed_event(...)` appropriately.
    """

    def __init__(self, llm_client, overlay):
        """
        :param llm_client:   An instance of LLMClient (core/llm_client.py)
        :param overlay:      An instance of Overlay (core/overlay.py)
        """
        self.llm_client = llm_client
        self.overlay = overlay

        # Track the currently focused text-control "Accessible" object, if any (Linux: pyatspi Accessible).
        self.current_focus = None

        # Cache the current text content of the focused field.
        self.current_text_cache = ""

        # For rate-limiting requests to the LLM
        self.last_text_update_time = 0
        self.update_delay = settings.LLM_UPDATE_DELAY  # e.g. 0.5 seconds

        # Timer used to schedule LLM calls after the user stops typing.
        self._idle_timer = None

    def on_focus_event(self, event):
        """
        Called by the OS-specific hooking code whenever focus changes.
        On Linux + pyatspi, you'd typically see:
            event.type = "object:state-changed:focused"
            event.detail1 == 1 means gained focus, 0 means lost focus.
            event.source is the Accessible object that gained or lost focus.
        
        :param event: The platform-specific event (e.g. a pyatspi event object).
        """
        try:
            # Check if this is focus gained or lost
            is_focus_gained = (event.detail1 == 1)

            if is_focus_gained:
                # If the newly focused object is an editable text role
                role_name = event.source.getRoleName().lower() if event.source else ""
                if "edit" in role_name or "text" in role_name:
                    # Mark this as our new focus
                    self.current_focus = event.source
                    # Grab the existing text from the field
                    self.current_text_cache = self._get_full_text(event.source)

                    # Optionally do an immediate LLM suggestion (for an empty or partial field)
                    self.query_llm_async()

                else:
                    # Not a text field => clear focus & hide overlay
                    self.current_focus = None
                    self.overlay.hide()

            else:
                # If losing focus from this object
                if self.current_focus == event.source:
                    # The object losing focus is the one we're tracking
                    self.current_focus = None
                    self.current_text_cache = ""
                    self.overlay.hide()

        except Exception:
            traceback.print_exc()

    def on_text_changed_event(self, event):
        """
        Called by the OS-specific hooking code whenever text changes in a field.
        On Linux + pyatspi, you'd see event.type in {"object:text-changed:insert","object:text-changed:delete"}.

        :param event: The platform-specific text-changed event.
        """
        try:
            # If we have a focus object and this event’s source is that same object
            if self.current_focus is not None and event.source == self.current_focus:
                # Update cache (full text).
                self.current_text_cache = self._get_full_text(event.source)

                # Bump the timestamp for our rate-limit check
                self.last_text_update_time = time.time()

                # Cancel any previous timer and schedule a new one
                if self._idle_timer is not None:
                    self._idle_timer.cancel()
                self._idle_timer = threading.Timer(self.update_delay, self._check_and_query_llm)
                self._idle_timer.start()
        except Exception:
            traceback.print_exc()

    def accept_suggestion(self, suggestion):
        """
        Inserts the given suggestion text into the currently focused text field
        if possible, or falls back to the clipboard-paste method.

        :param suggestion: A string from the LLM to be appended or used as final text.
        """
        if not self.current_focus:
            return

        # Attempt direct text insertion via the accessibility EditableText interface
        try:
            new_full_text = self._compute_new_text(self.current_text_cache, suggestion)
            if self._set_text_contents(self.current_focus, new_full_text):
                # If we succeeded, update the local cache so we stay consistent
                self.current_text_cache = new_full_text
                return
        except Exception:
            pass  # If direct set fails, we fallback

        # If we get here, attempt fallback approach
        self._clipboard_paste(suggestion)

    def _check_and_query_llm(self):
        """
        Called after a small delay from the last text-changed event.
        If no further text changes have occurred in the meantime,
        we issue a request to the LLM for a suggestion.
        """
        elapsed = time.time() - self.last_text_update_time
        if elapsed >= self.update_delay:
            # Enough idle time => let's fetch an LLM suggestion
            self.query_llm_async()

    def query_llm_async(self):
        """
        Do the LLM request in a background thread so we don’t block the main event loop.
        Upon completion, show or hide the overlay with the resulting suggestion.
        """
        if not self.current_focus:
            return

        def run_llm():
            try:
                # Optionally gather more context:
                #   label/placeholder => event.source.name or .getParent().getName()
                #   window title => ...
                # For minimal example, just pass the current text:
                suggestion = self.llm_client.get_suggestion(self.current_text_cache)

                if suggestion:
                    # Calculate where to show the overlay (e.g., bounding box)
                    bbox = self._get_bounding_box(self.current_focus)
                    x, y, w, h = bbox
                    # Example: put the overlay just below the field
                    overlay_x = x
                    overlay_y = y + h

                    # Show the suggestion
                    self.overlay.show_suggestion(suggestion, x=overlay_x, y=overlay_y)
                else:
                    self.overlay.hide()

            except Exception:
                traceback.print_exc()
                self.overlay.hide()

        thread = threading.Thread(target=run_llm, daemon=True)
        thread.start()

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def _get_full_text(self, accessible_obj):
        """
        Returns the entire text content from an Accessibility object (if possible).
        On Linux/pyatspi, you'd do something like:
            txt_iface = accessible_obj.queryText()
            return txt_iface.getText(0, -1)
        """
        # This is OS-specific logic. Stubbed here to illustrate.
        try:
            txt_iface = accessible_obj.queryText()
            return txt_iface.getText(0, -1)
        except Exception:
            return ""

    def _set_text_contents(self, accessible_obj, new_text):
        """
        Attempts to directly set the entire text content via the EditableText interface.
        Returns True on success, False otherwise.
        """
        try:
            editable = accessible_obj.queryEditableText()
            editable.setTextContents(new_text)
            return True
        except Exception:
            return False

    def _clipboard_paste(self, text):
        """
        Fallback approach: set the clipboard to `text`, then paste (e.g. via xdotool or wtype).
        Implementation typically calls out to a small shell script or subprocess.

        For example:
          1) backup the current clipboard
          2) copy new text into the clipboard
          3) simulate 'Ctrl+V'
          4) restore old clipboard
        """
        # This is left as a stub to be implemented in hooking/paste_utils.sh or similar.
        print(f"[DEBUG] Fallback paste for: {text}")

    def _compute_new_text(self, current_text, suggestion):
        """
        Defines how to merge the current text and the LLM's suggestion.
        For an MVP, you may simply return `suggestion` or
        treat `suggestion` as the 'completion' appended to `current_text`.
        """
        # Example: if suggestion starts with current_text, just use suggestion
        if suggestion.startswith(current_text):
            return suggestion
        # Otherwise, you might want something more advanced. For now, let’s assume an overwrite:
        return suggestion

    def _get_bounding_box(self, accessible_obj):
        """
        Returns (x, y, width, height) for the bounding box on screen coordinates.

        On Linux/pyatspi:
            comp = accessible_obj.queryComponent()
            return comp.getExtents(pyatspi.DESKTOP_COORDS)
        """
        try:
            comp = accessible_obj.queryComponent()
            x, y, w, h = comp.getExtents(0)  # 0 = pyatspi.DESKTOP_COORDS
            return x, y, w, h
        except Exception:
            # Fallback if we can’t get bounding box
            return 0, 0, 50, 20
