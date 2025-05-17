"""Configuration values for the autocompleter."""

# Time in seconds to wait after the last text update before querying the LLM
LLM_UPDATE_DELAY = 0.5

# Default endpoint for the language model service
LLM_ENDPOINT = "http://localhost:8000/v1/completions"
