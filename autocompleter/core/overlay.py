"""
Minimal PyQt Overlay for showing an autocomplete suggestion.

Usage example (running this file directly):
    python overlay.py
"""

import sys

from PyQt5 import QtCore, QtWidgets

class OverlayWindow(QtWidgets.QWidget):
    """
    A small, borderless, always-on-top window that displays a suggestion
    and an 'Accept' button. When the user clicks Accept, it calls self.on_accept(suggestion).
    """
    def __init__(self, on_accept=None, parent=None):
        super().__init__(parent)
        self.on_accept = on_accept

        # Remove window decorations, keep on top, disable taskbar entry
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )

        # Basic widgets
        self.label = QtWidgets.QLabel("No suggestion", self)
        self.button = QtWidgets.QPushButton("Accept", self)

        # Layout
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.label)
        layout.addWidget(self.button)
        self.setLayout(layout)

        # Connect button
        self.button.clicked.connect(self._handle_accept_clicked)

        # Optional: some basic styling
        self.setStyleSheet("""
            background-color: #F8F8F8;
            border: 1px solid #CCC;
            border-radius: 4px;
        """)

    def show_suggestion(self, text, x=0, y=0):
        """
        Show the overlay near (x, y), displaying 'text'.
        Coordinates are relative to the screen (desktop) in this example.
        """
        self.label.setText(text)
        self.adjustSize()

        # Position the overlay just above the text field (or anywhere you like).
        # For example, (x, y - height).
        new_x = x
        new_y = y - self.height()
        self.move(new_x, new_y)

        self.show()

    def _handle_accept_clicked(self):
        """
        Invoked when user clicks the Accept button.
        """
        if self.on_accept:
            # Pass the label text back to the callback
            suggestion = self.label.text()
            self.on_accept(suggestion)

        # Hide the overlay after accepting
        self.hide()


class Overlay:
    """
    A higher-level wrapper that:
      - Owns the QApplication (if needed)
      - Owns the OverlayWindow instance
      - Exposes simple .show_suggestion(...) and .hide() methods

    Integration Steps in your code:
      1. Create one Overlay instance (with a callback to accept suggestions).
      2. Start the Qt event loop once (often in main.py or similar).
      3. Use overlay.show_suggestion(...) from your hooking/core logic.
    """

    def __init__(self, on_accept=None):
        """
        :param on_accept: a function callback(suggestion_string) -> None
                          to be called when the user clicks "Accept."
        """
        # If an application instance doesn't exist, create one.
        # If it already exists (e.g., your main.py created it), we reuse that.
        if not QtWidgets.QApplication.instance():
            self.app = QtWidgets.QApplication(sys.argv)
        else:
            self.app = QtWidgets.QApplication.instance()

        # Create the window
        self.window = OverlayWindow(on_accept=on_accept)
        self.window.hide()  # hidden by default

    def show_suggestion(self, text, x=0, y=0):
        """Show an autocomplete suggestion near the given screen coords."""
        self.window.show_suggestion(text, x, y)

    def hide(self):
        """Hide the overlay window."""
        self.window.hide()

    def exec_(self):
        """
        Blocking call to start the Qt event loop.
        If you're embedding this in a larger app that already runs the loop,
        you won't call this. Instead, let the main loop run from your app code.
        """
        sys.exit(self.app.exec_())


# ------------------------
# Example standalone usage
# ------------------------
if __name__ == "__main__":
    def on_accept_callback(suggestion):
        print("[DEBUG] Accepted suggestion:", suggestion)
        # You could call into AutocompleteCore here, e.g.,
        # core.accept_suggestion(suggestion)

    overlay = Overlay(on_accept=on_accept_callback)

    # Show a sample suggestion at coordinates (400, 400) on screen.
    overlay.show_suggestion("Example completion text", 400, 400)

    print("[DEBUG] Starting event loop.")
    overlay.exec_()
