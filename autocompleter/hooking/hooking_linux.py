"""hooking_linux.py

Linux-specific accessibility hooks using pyatspi. This module registers
listeners for focus and text-change events and forwards the raw events to
``AutocompleteCore``. The AT-SPI event loop runs in a background thread so that
other event loops (e.g. PyQt) can continue running on the main thread.
"""

import threading
import pyatspi

_core = None


def start_linux_hooks(core):
    """Register AT-SPI listeners and start the event loop in a thread."""
    global _core
    _core = core

    pyatspi.Registry.registerEventListener(
        on_focus_event, "object:state-changed:focused"
    )
    pyatspi.Registry.registerEventListener(
        on_text_changed_event, "object:text-changed:insert"
    )
    pyatspi.Registry.registerEventListener(
        on_text_changed_event, "object:text-changed:delete"
    )

    thread = threading.Thread(target=pyatspi.Registry.start, daemon=True)
    thread.start()
    return thread


def on_focus_event(event):
    """Forward focus events to the core."""
    if _core:
        _core.on_focus_event(event)


def on_text_changed_event(event):
    """Forward text-change events to the core."""
    if _core:
        _core.on_text_changed_event(event)
