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
    This function should be called once from main.py after the core is initialized.
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

    # Launch the AT-SPI event loop. This call is blocking, so if your application
    # requires concurrency, you might want to run this in a background thread.
    pyatspi.Registry.start()


def on_focus_changed(event):
    """
    Callback for focus changes. We check if the new focus is an editable text
    field and, if so, notify the core system.
    """
    # event.detail1 == 1 => gained focus
    if event.detail1 == 1:
        source = event.source
        role_name = source.getRoleName().lower()

        # Exclude password fields or non-editable text
        if "password" in role_name or not is_editable_text(source):
            # Hide any existing overlay, focus is invalid for suggestions
            _core.on_focus_changed(None)  # or pass a special event, or just hide overlay
            return

        # This is a valid text field => pass to the core
        info = {
            "role": source.getRoleName(),
            "name": source.name,
            "full_text": get_all_text_safe(source)
        }

        _core.on_focus_changed(info)
    else:
        # Focus lost
        # Optionally tell core to hide suggestions or reset state
        _core.on_focus_changed(None)


def on_text_changed(event):
    """
    Callback for text insertions or deletions. We only handle events from the
    currently focused text field. Then, we update the core with the new text.
    """
    # If there's no core or no source, do nothing
    if not _core or not event.source:
        return

    source = event.source
    if not is_editable_text(source):
        return

    # We fetch the entire text from the field:
    new_text = get_all_text_safe(source)

    # Prepare an info dict. You could pass the raw event object if you prefer.
    info = {
        "role": source.getRoleName(),
        "name": source.name,
        "new_text": new_text
        # ... other info if needed
    }

    _core.on_text_changed(info)


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


# ------------------------------------------------------------------------------
# Example helper that your AutocompleteCore might call:
# ------------------------------------------------------------------------------

def insert_suggestion(accessible_obj, base_text: str, suggestion: str):
    """
    Attempt to insert `suggestion` into the text field represented by `accessible_obj`.
    This merges or simply replaces text depending on your design.
    
    `base_text` is the text currently in the field, so you can do merges if needed.
    """
    # Example logic: if suggestion starts with base_text, or do some fancy logic.
    new_text = suggestion  # or: base_text + suggestion, etc.

    ok = direct_set_text_contents(accessible_obj, new_text)
    if not ok:
        # Fallback
        fallback_insert_text(new_text)
