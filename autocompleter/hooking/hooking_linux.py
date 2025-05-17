"""
hooking_linux.py

Implements Linux-specific hooking using pyatspi to intercept focus changes
and text-change events. If direct text insertion fails, falls back to
a 'clipboard + paste' approach for injecting text.
"""

import pyatspi
import subprocess
import time
import threading

# If you plan to support Wayland as well as X11, you may need
# to adapt the 'simulate_paste' command to your environment
# (xdotool vs wtype vs ydotool, etc.).
# Below is a simple X11 example using xdotool + xclip.
SIMULATE_PASTE_CMD = ["xdotool", "key", "--clearmodifiers", "ctrl+v"]

# For copying text into clipboard on X11:
COPY_TO_CLIP_CMD = ["xclip", "-selection", "clipboard"]
READ_CLIP_CMD    = ["xclip", "-selection", "clipboard", "-o"]


# Global references for our event listeners. We hold them at module scope
# but could also store them in a small class if you prefer.
_core = None  # Will store a reference to the AutocompleteCore instance


def start_linux_hooks(core):
    """
    Entry point: register AT-SPI event listeners and begin listening.
    Runs the AT-SPI event loop in a background thread to avoid blocking the Qt event loop.
    """
    global _core
    _core = core

    # Register event listeners
    pyatspi.Registry.registerEventListener(
        on_focus_changed,
        "object:state-changed:focused"
    )
    pyatspi.Registry.registerEventListener(
        on_text_changed,
        "object:text-changed:insert"
    )
    pyatspi.Registry.registerEventListener(
        on_text_changed,
        "object:text-changed:delete"
    )

    # Start AT-SPI event loop in a background thread
    def run_at_spi_loop():
        try:
            pyatspi.Registry.start()
        except Exception as e:
            print(f"Error in AT-SPI event loop: {e}")

    # Create and start the thread
    at_spi_thread = threading.Thread(target=run_at_spi_loop, daemon=True)
    at_spi_thread.start()


def on_focus_changed(event):
    """
    Callback for focus changes. We check if the new focus is an editable text
    field and, if so, notify the core system.
    """
    try:
        # Check if this is focus gained or lost
        is_focus_gained = (event.detail1 == 1)

        if is_focus_gained:
            # If the newly focused object is an editable text role
            role_name = event.source.getRoleName().lower() if event.source else ""
            if "edit" in role_name or "text" in role_name:
                # Pass the raw event to core
                _core.on_focus_event(event)
            else:
                # Not a text field => hide overlay
                _core.on_focus_event(event)

        else:
            # If losing focus from this object
            if _core.current_focus == event.source:
                # The object losing focus is the one we're tracking
                _core.on_focus_event(event)

    except Exception as e:
        print(f"Error in focus change handler: {e}")


def on_text_changed(event):
    """
    Callback for text insertions or deletions. We only handle events from the
    currently focused text field. Then, we update the core with the new text.
    """
    try:
        # If we have a focus object and this event's source is that same object
        if _core.current_focus is not None and event.source == _core.current_focus:
            # Pass the raw event to core
            _core.on_text_changed_event(event)

    except Exception as e:
        print(f"Error in text change handler: {e}")


def is_editable_text(accessible_obj) -> bool:
    """
    Returns True if the object is an editable text field, ignoring protected/password fields.
    """
    try:
        # Basic check: object has an EditableText interface
        # and is not read-only or password-protected
        state_set = accessible_obj.getState()
        if not state_set.contains(pyatspi.STATE_EDITABLE):
            return False

        # Some objects may present as ROLE_TEXT or ROLE_ENTRY, etc.
        # If you want to be thorough, you can check the role constants, e.g.:
        # from pyatspi import ROLE_ENTRY, ROLE_TEXT
        # role = accessible_obj.getRole()
        # if role not in [ROLE_ENTRY, ROLE_TEXT, ROLE_EDITABLE_TEXT]:
        #     return False

        # Also skip if it's protected (like a password)
        if state_set.contains(pyatspi.STATE_PROTECTED):
            return False

        # If we got here, it likely supports text editing
        return True
    except:
        return False


def get_all_text_safe(accessible_obj) -> str:
    """
    Safely retrieves all text from the accessible object.
    If there's no text interface, returns empty string.
    """
    try:
        txt_iface = accessible_obj.queryText()
        return txt_iface.getText(0, -1)
    except NotImplementedError:
        # No text interface
        return ""


# ------------------------------------------------------------------------------
# Clipboard+Paste fallback functions
# ------------------------------------------------------------------------------

def fallback_insert_text(new_text: str):
    """
    Fallback approach for inserting text by:
      1. Saving current clipboard
      2. Copying `new_text` to clipboard
      3. Simulating Ctrl+V
      4. Restoring original clipboard
    """
    # Save old clipboard
    old_clipboard = ""
    try:
        old_clipboard = subprocess.check_output(READ_CLIP_CMD, text=True)
    except subprocess.CalledProcessError:
        # If there's no initial clipboard content or xclip isn't working
        old_clipboard = ""

    # Copy the new text
    try:
        copy_proc = subprocess.Popen(COPY_TO_CLIP_CMD, stdin=subprocess.PIPE, text=True)
        if copy_proc and copy_proc.stdin:
            copy_proc.stdin.write(new_text)
            copy_proc.stdin.close()
        copy_proc.wait()
    except subprocess.CalledProcessError:
        pass

    # Simulate Ctrl+V
    # If you're on Wayland, this won't work unless using xwayland or you have a
    # different approach. For example, wtype, ydotool, etc.
    try:
        subprocess.run(SIMULATE_PASTE_CMD, check=True)
    except subprocess.CalledProcessError:
        pass

    # Give a short delay to allow the paste event to complete
    time.sleep(0.1)

    # Restore old clipboard
    try:
        restore_proc = subprocess.Popen(COPY_TO_CLIP_CMD, stdin=subprocess.PIPE, text=True)
        if restore_proc and restore_proc.stdin:
            restore_proc.stdin.write(old_clipboard)
            restore_proc.stdin.close()
        restore_proc.wait()
    except subprocess.CalledProcessError:
        pass


def direct_set_text_contents(accessible_obj, new_text: str) -> bool:
    """
    Attempts to directly set the entire contents of the text field
    using the EditableText interface. Returns True if successful, False otherwise.
    """
    try:
        editable_iface = accessible_obj.queryEditableText()
        # Overwrite the entire text
        editable_iface.setTextContents(new_text)
        return True
    except:
        # Could be NotImplementedError or the object blocking changes
        return False
