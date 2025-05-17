from .config import settings
from .core.core import AutocompleteCore
from .core.llm_client import LLMClient
from .core.overlay import Overlay
from .hooking.hooking_linux import start_linux_hooks


def main():
    """Entry point for the autocompleter."""
    llm_client = LLMClient()
    overlay = Overlay()
    core = AutocompleteCore(llm_client, overlay)
    start_linux_hooks(core)
    print("Autocompleter started (stub).")


if __name__ == "__main__":
    main()
