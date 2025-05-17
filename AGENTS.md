
## High-Level Goals

1. **Intercept text-focus changes** system-wide via **AT-SPI** (no custom hooking, minimal permissions).
2. **Detect and track typed text** by subscribing to *accessibility text-change events* (instead of raw keypress hooks).
3. **Fetch additional context** from the accessibility tree (control label, window title, partial text) to feed the LLM.
4. **Query LLM** for suggestions after a short idle/buffer period.
5. **Inject completions** either by setting the accessible text value if supported or, if not, by fallback “clipboard + paste.”
6. **Build a simple overlay** using a lightweight, cross-platform approach (e.g. a WebView or minimal native window) that’s easy to port.

Implementation is **modular**:

1. **Linux-specific hooking** (AT-SPI library usage).
2. **Core logic** (rate-limiting, LLM calls, overlay coordination).
3. **Overlay UI** (a minimal cross-platform framework or a WebView).

We focus on **Linux** for v1, but code structure is prepared for future Windows/macOS expansions.

---

## 1. Accessibility-Driven MVP

### 1.1 AT-SPI Focus & Text-Change Events

* Use **pyatspi** (Python) for rapid iteration:

  * `pyatspi.Registry.registerEventListener(onFocusEvent, "object:state-changed:focused")`
  * `pyatspi.Registry.registerEventListener(onTextChanged, "object:text-changed:*")`
* `onFocusEvent(evt)` → check:

  * `evt.detail1 == 1` means gained focus.
  * `evt.source.getRole() in { ROLE_ENTRY, ROLE_TEXT, ROLE_EDITABLE_TEXT }` (and `STATE_EDITABLE in evt.source.getState()`).
* `onTextChanged(evt)` → indicates typed characters or text modifications.

  * Example signals: `"object:text-changed:insert"`, `"object:text-changed:delete"`.
  * Use `evt.any_data` (the inserted text) or poll `evt.source.queryText().getText(0, -1)` for the entire field content.

### 1.2 Reading Partial Text

* Once a text field is in focus, keep track of its **full text** by calling `source.queryText().getText(0, -1)` whenever an insert event arrives.
* Use a **small cooldown** (\~300–500 ms) after each text-changed event to trigger an **LLM** request.

### 1.3 Setting the Text (Insertion)

* **Preferred approach**: Use AT-SPI’s text interface to set the entire string if the control supports it (some do, some don’t).

  * For instance, `AccessibleText.setTextContents(newFullText)`.
  * If the control denies this (read-only to AT?), fallback to the “clipboard + paste” approach below.

### 1.4 Fallback “Clipboard + Paste”

* Implement a minimal helper (Python or shell) that:

  1. Backs up the current clipboard (`xsel` or `wl-paste`).
  2. Sets the new suggestion text (`wl-copy` or `xclip -selection clipboard`).
  3. Simulates a Paste event:

     * On X11: `xdotool key --clearmodifiers ctrl+v`
     * On Wayland: `wtype --paste` or `ydotool key ctrl+v` (depends on environment).
  4. Restores the old clipboard after a short delay.
* This approach bypasses injecting keystrokes one by one.

---

## 2. MVP Core Logic

### 2.1 Event Manager (Python Example)

```python
import pyatspi
import time
import threading

class AutocompleteCore:
    def __init__(self, llm_client, overlay):
        self.llm_client = llm_client
        self.overlay = overlay
        self.current_focus = None
        self.current_text_cache = ""
        self.last_text_update_time = 0
        self.update_delay = 0.5  # half a second

    def on_focus_event(self, event):
        if event.detail1 == 1:  # gained focus
            role = event.source.getRoleName()
            if "edit" in role.lower() or "text" in role.lower():
                # It's a text field
                self.current_focus = event.source
                self.current_text_cache = self.get_full_text(event.source)
                # Possibly request an initial LLM suggestion with zero text if desired
                self.query_llm_async(self.current_text_cache)
            else:
                # not a text field
                self.current_focus = None
                self.overlay.hide()

    def on_text_changed_event(self, event):
        if self.current_focus is not None and event.source == self.current_focus:
            # Update cache
            self.current_text_cache = self.get_full_text(event.source)
            self.last_text_update_time = time.time()
            # In the background, wait ~0.5 sec from last update before sending LLM request
            # Could do it via a small timer thread
            threading.Timer(self.update_delay, self.check_and_query_llm).start()

    def check_and_query_llm(self):
        # If no new keystrokes have occurred for last 0.5s => do LLM request
        if time.time() - self.last_text_update_time >= self.update_delay:
            self.query_llm_async(self.current_text_cache)

    def query_llm_async(self, partial_text):
        suggestion = self.llm_client.get_suggestion(partial_text)
        if suggestion:
            # Show overlay near the bounding box
            bbox = self.get_bounding_box(self.current_focus)
            self.overlay.show(suggestion, bbox)
        else:
            self.overlay.hide()

    def accept_suggestion(self, suggestion):
        # Try direct setTextContents
        if self.can_set_directly(self.current_focus):
            new_text = self.compute_new_text(self.current_text_cache, suggestion)
            self.set_text_contents(self.current_focus, new_text)
        else:
            # fallback
            self.clipboard_paste(suggestion)

    # Helpers
    def get_full_text(self, obj):
        # safe query
        txt = obj.queryText()
        return txt.getText(0, -1)

    def get_bounding_box(self, obj):
        ext = obj.queryComponent()
        x, y, w, h = ext.getExtents(pyatspi.DESKTOP_COORDS)
        return (x, y, w, h)

    def can_set_directly(self, obj):
        # attempt if there's a text interface
        # some controls might not allow write
        try:
            txt = obj.queryText()
            # maybe do a test write or check if it's read-only
            # for MVP, assume yes
            return True
        except:
            return False

    def set_text_contents(self, obj, new_text):
        # carefully replace entire text
        try:
            txt = obj.queryEditableText()
            txt.setTextContents(new_text)
        except:
            pass  # fallback handled upstream

    def compute_new_text(self, current, suggestion):
        # merge logic e.g. if suggestion starts with current text
        return suggestion

    def clipboard_paste(self, text):
        # call out to a script that handles setting clipboard + xdotool ctrl+v, etc.
        pass
```

### 2.2 LLM Client (Stub)

```python
class LLMClient:
    def get_suggestion(self, partial_text):
        # MVP: simple local logic or remote call
        # e.g. an HTTP POST to your model endpoint
        # "prompt" = partial_text, "some additional context"
        return call_your_llm_service(partial_text)
```

### 2.3 Overlay UI

* For speed, build a minimal **Python** + **PyQt** or **GTK** “always on top” borderless window.
* Position it near `(x, y - overlay_height - margin)` from the bounding box.
* Show the suggested text. If user clicks or triggers an accept event, call `autocompleteCore.accept_suggestion(...)`.

Or a **WebView** approach with e.g. Flask + WebView libraries, but for MVP you can keep it simpler in native widget frameworks.

---

## 3. Expanding to Windows & macOS Later

Once the Linux MVP is stable:

1. **Windows hooking**: Replace the `pyatspi` logic with `pywin32` + UIA or `SetWinEventHook`.

   * Also switch from `queryText()` to `UIAutomation`’s `IUIAutomationTextPattern`.
   * The rest of the core logic is the same.

2. **macOS hooking**: Replace with `pyobjc` and `AXObserverCreate(...)` to capture `kAXFocusedUIElementChangedNotification`.

   * Use `AXValue` to read/write text for controls that allow it.

In each case, your core logic remains the same. You just replicate the “event bridging” from OS to the `AutocompleteCore`.

---

## 4. Additional Quick Wins

1. **Use the Accessibility Tree** for extra context:

   * The label or placeholder for the text field (`NAME` or `DESCRIPTION` in AT-SPI)
   * The parent window’s title.
   * Pass these to the LLM to improve suggestion accuracy without requiring screenshots.

2. **Cache common expansions**:

   * If user focuses a “Name” field that was used previously, you might skip the LLM roundtrip or show old suggestions.

3. **Security**:

   * Exclude password fields: If `ROLE_PASSWORD_TEXT` or `STATE_PROTECTED`, skip hooking or suggestions.

4. **Focus on an easy acceptance mechanism**:

   * A single button or click in the overlay is fine for MVP; you can add Tab or a custom hotkey if necessary.
   * If the text field sees the key event “Tab,” that might move focus. To handle that, you can intercept at the overlay or at the accessibility level.

5. **Minimal microservices**:

   * For the LLM, start with a single local model or a basic remote endpoint, so you’re not blocked by DevOps complexity.

---

## 5. Summary

**MVP**:

* **Linux-first** approach using **AT-SPI** (via Python `pyatspi`) to detect text focus, track typed text, and optionally set text directly.
* **Fallback** to “clipboard + paste” if direct setting fails.
* **Simple overlay** in a Python GUI framework or a small WebView, displayed near the text field bounding box.
* **LLM** calls done after an idle delay to keep inference overhead low.

**Future**:

* Port hooking code to Windows/macOS, but preserve the same “Core” logic.
* Possibly unify the overlay with a cross-platform UI library or a single WebView approach.

This plan is **minimal** to implement while preserving a path to scale up. By skipping raw key hooking in favor of text-change notifications, you **avoid** complicated permission issues, can move faster, and get *complete text strings* instantly.



Below is an example **Python-based** project structure for the Linux MVP, showing how to organize the files, their responsibilities, and how they relate to each other. This layout is both minimal and modular:

```
autocompleter/
├── __init__.py
├── main.py
├── hooking/
│   ├── __init__.py
│   ├── hooking_linux.py
│   └── paste_utils.sh
├── core/
│   ├── __init__.py
│   ├── core.py
│   ├── llm_client.py
│   └── overlay.py
├── config/
│   └── settings.py
└── requirements.txt
```

Below is an explanation of each component:

---

## Top Level

* **`autocompleter/`**

  * The main Python package folder, containing all source code.

* **`__init__.py`**

  * Makes the `autocompleter` directory importable as a Python package.

* **`main.py`**

  * The primary entry point to launch the autocomplete daemon on Linux.
  * Responsible for:

    * Parsing CLI arguments (if any).
    * Initializing the hooking logic (`hooking_linux.py`).
    * Creating and configuring the core system (`core.py`, `llm_client.py`, `overlay.py`).
    * Starting the event loop (`pyatspi.Registry.start()`).
  * Could also handle logging setup, error handling, or user prompts for additional configuration.

* **`requirements.txt`**

  * Lists Python dependencies (e.g., `pyatspi`, any GUI framework for the overlay, HTTP libraries for the LLM, etc.).

---

## `hooking/` Directory

This directory contains the **OS-specific** hooking and fallback logic for Linux.

1. **`hooking_linux.py`**

   * Implements:

     * **Focus detection** using AT-SPI (`pyatspi`) event listeners, e.g. `object:state-changed:focused`.
     * **Text-change** detection using AT-SPI signals like `object:text-changed:insert`.
     * **Direct text insertion** via `obj.queryEditableText().setTextContents(...)` if allowed.
     * A **bridge** to the core system: e.g., calls `core.onFocusChanged(...)`, `core.onTextChanged(...)`.
   * Exports a function like `start_linux_hooks(core_instance)` that:

     1. Registers event listeners with `pyatspi.Registry`.
     2. Launches `pyatspi.Registry.start()` on the main thread or in a background thread.

2. **`paste_utils.sh`** (optional or you can do it in Python)

   * A small bash script to perform “clipboard + paste” fallback:

     1. Capture current clipboard with `xclip` or `wl-paste`.
     2. Set new suggestion text with `wl-copy` or `xclip`.
     3. Simulate `ctrl+v` using `xdotool` (X11) or `wtype` (Wayland).
     4. Restore original clipboard.
   * This script is invoked by the hooking logic or the core if direct setting fails.

*(Note: you could also implement the clipboard + paste approach in pure Python, e.g., using `subprocess.run(...)` calls to the same tools. Up to preference.)*

---

## `core/` Directory

Holds **platform-agnostic** logic that can be reused on Windows/macOS later.

1. **`core.py`**

   * Defines the primary class, e.g., `AutocompleteCore`, containing:

     * Methods like `onFocusChanged(obj)`, `onTextChanged(obj, new_text)`.
     * A buffer/timer for making LLM calls after idle intervals.
     * Logic to compute final text merges (if needed).
     * A method `acceptSuggestion(...)` that attempts direct text set, or falls back to calling `paste_utils.sh`.

2. **`llm_client.py`**

   * Handles communication with your chosen LLM (local or remote).
   * Exports a class like `LLMClient` with `get_suggestion(partial_text, context_info)`.

3. **`overlay.py`**

   * A minimal UI to show suggestions on top of the screen, e.g., a small borderless PyQt/GTK window (or a WebView).
   * `Overlay` class might provide:

     * `show_suggestion(text, x, y)` – positions near bounding box or cursor.
     * `hide()` – hides the window.
     * Optionally a callback or signal for when the user clicks “Accept” in the overlay.

---

## `config/` Directory

1. **`settings.py`**

   * Contains global configuration variables:

     * **Rate limiting** intervals (e.g. `LLM_UPDATE_DELAY = 0.5`).
     * **Paths** or environment detection for `paste_utils.sh`.
     * LLM endpoint or local model paths, if needed.
     * Overlays style config, e.g. font size, colors.

---

## Flow Summary

1. **`main.py`**

   * Reads `config/settings.py`, sets up logging, builds `LLMClient`, `AutocompleteCore`, `Overlay`.
   * Calls `start_linux_hooks(core_instance)`.
   * Enters main loop (`pyatspi.Registry.start()`).

2. **`start_linux_hooks(core_instance)`** (in `hooking_linux.py`)

   * Registers `onFocusChanged(event)` and `onTextChanged(event)` callbacks.
   * Inside callbacks, calls `core_instance.onFocusChanged(...)` or `core_instance.onTextChanged(...)`.

3. **`AutocompleteCore`** (in `core.py`)

   * Maintains partial text buffers, calls `LLMClient.get_suggestion(...)` after idle.
   * In `acceptSuggestion(suggestion)`, tries direct `setTextContents`; if it fails, calls `paste_utils.sh` or an equivalent Python function.

4. **`Overlay`** (in `overlay.py`)

   * Receives suggestions to display. If the user selects or presses “accept,” it calls back into `AutocompleteCore.acceptSuggestion(...)`.

5. **`LLMClient`** (in `llm_client.py`)

   * Makes a remote or local request to an LLM. Returns the best suggestion string.

6. **`paste_utils.sh`** (or a Python-based fallback)

   * Manages the clipboard → paste → restore cycle if direct text set is unavailable.

---

## Advantages of This Structure

* **Clear Separation**:

  * The `hooking/` subpackage is purely about Linux-specific accessibility event handling.
  * The `core/` subpackage is OS-agnostic and can later be recompiled or reused under Windows/macOS hooking layers.
* **Easy to Extend**:

  * For Windows/macOS, just add `hooking_windows.py` or `hooking_macos.py` in the same `hooking/` folder, keep `core/` identical.
* **Simple Overlay Replacement**:

  * If you switch from PyQt to a WebView in future, you only replace `overlay.py` while keeping the rest intact.
* **Config-Driven**:

  * `settings.py` for environment toggles, logging, or advanced features (like toggling screenshot capture if you add it later).

---

## Future Enhancements

1. **Logging & Telemetry**:

   * A `logger.py` in `core/` or top-level for capturing usage stats (e.g., suggestion acceptance rate).
2. **Screenshot Flow**:

   * Later, if you add screenshot-based context, put that logic in `hooking_linux.py` (or a separate `screenshots.py`) and pass images to `core.py` → `llm_client.py`.
3. **Tests**:

   * A `tests/` folder with unit tests for `core.py` logic, mock LLM calls, and minimal integration tests hooking AT-SPI in a CI environment.

---

**In summary**, this structure focuses on a **Python-first, Linux-first** approach—maximizing quick development and minimal friction. As the MVP matures, you can port the hooking layer to other OSes while reusing the same core logic, overlay design, and LLM client.
