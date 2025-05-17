"""
Main entry point for the Autocompleter MVP on Linux.
"""

import sys
import signal
import logging

# Third-party
import pyatspi

# Local imports from our package structure
from .config import settings
from .core.core import AutocompleteCore
from .core.llm_client import LLMClient
from .core.overlay import Overlay
from .hooking.hooking_linux import start_linux_hooks

def main():
    """
    Entry point that launches the autocompleter daemon on Linux.
    """
    # Configure logging (adjust level as needed)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    logger = logging.getLogger(__name__)

    logger.info("Initializing LLM client, overlay, and core logic...")
    llm_client = LLMClient()
    overlay = Overlay()
    core = AutocompleteCore(llm_client, overlay)

    logger.info("Starting Linux accessibility hooks...")
    start_linux_hooks(core)

    # Set up signal handlers for clean exit (e.g., Ctrl+C)
    def handle_signal(signum, frame):
        logger.info("Received signal %s. Shutting down gracefully.", signum)
        pyatspi.Registry.stop()  # Stop the AT-SPI event loop
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Launching the AT-SPI registry event loop. Press Ctrl+C to exit.")
    # This call blocks and processes accessibility events indefinitely
    pyatspi.Registry.start()


if __name__ == "__main__":
    main()
