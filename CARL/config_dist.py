"""
Configuration settings for TaxonGPT LLM integration.

SETUP REQUIRED:
  1. Replace <your Groq API key here> with your actual key (starts with gsk_).
  2. Save this file.  TaxonGPT reads it on every launch.

To obtain a free Groq API key see Installation_Guide.html.
"""

class LLMConfig:
    def __init__(
        self,
        model,
        temperature=None,
        num_predict=None,
        num_ctx=None,
        style_guide="",
        think=False,
        use_chat=False
    ):
        self.model = model
        self.temperature = temperature
        self.num_predict = num_predict
        self.num_ctx = num_ctx
        self.style_guide = style_guide
        self.think = think
        self.use_chat = use_chat

    def to_options(self):
        options = {}
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.num_predict is not None:
            options["num_predict"] = self.num_predict
        if self.num_ctx is not None:
            options["num_ctx"] = self.num_ctx
        if self.think:
            options["think"] = True
        return options


# ============================================================
# GLOBAL SETTINGS
# ============================================================

KEEP_ALIVE = "30m"
STYLE_GUIDE_PATH = "minimal_style_guide.md"

# ----------------------------------
# USER CONFIGURATION — EDIT BELOW
# ----------------------------------

DEFAULT_PROVIDER = "groq"
API_KEY = "<your Groq API key here>"

DEFAULT_MODELS = {
    "output":       "llama-3.3-70b-versatile",
    "verification": "openai/gpt-oss-safeguard-20b",
    "chat":         "meta-llama/llama-4-scout-17b-16e-instruct",
}
