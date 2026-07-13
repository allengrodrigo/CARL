"""
LLM Interface for TaxonAI.

Responsibilities:
- Route calls to the correct provider based on model name prefix
- Handle all deterministic LLM interactions
- Provide an optional chat interface for conversational features

Model naming convention:
  model:tag              → Ollama local model  (e.g. "llama3.2:1b")
  groq/model             → Groq cloud
  openai/model           → OpenAI
  huggingface/org/model  → HuggingFace Inference API
  anthropic/model        → Anthropic Messages API
  google/model           → Google Gemini API
  openrouter/org/model   → OpenRouter
  bare-name (no prefix)  → Groq (legacy backwards-compatible default)
"""

import re
import time

# ── Configuration types ───────────────────────────────────────────────────────

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


# Keep the model loaded in memory between calls.
# Options: "5m", "30m", "-1" (indefinite), or 0 (unload immediately).
KEEP_ALIVE = "30m"

# Legacy fallback API key — managed via taxongpt_settings.json in current installs.
API_KEY = ""

DEFAULT_PROVIDER = "groq"

DEFAULT_MODELS = {
    "output":       "meta-llama/llama-4-scout-17b-16e-instruct",
    "verification": "qwen/qwen3-32b",
    "chat":         "meta-llama/llama-4-scout-17b-16e-instruct",
}

# ── Provider registry ─────────────────────────────────────────────────────────
_PROVIDERS = {
    "groq":        {"base_url": "https://api.groq.com/openai/v1/chat/completions",                         "format": "openai"},
    "openai":      {"base_url": "https://api.openai.com/v1/chat/completions",                               "format": "openai"},
    "huggingface": {"base_url": "https://router.huggingface.co/v1/chat/completions",                        "format": "openai"},
    "anthropic":   {"base_url": "https://api.anthropic.com/v1/messages",                                    "format": "anthropic"},
    "google":      {"base_url": "https://generativelanguage.googleapis.com/v1beta/models",                  "format": "google"},
    "openrouter":  {"base_url": "https://openrouter.ai/api/v1/chat/completions",                            "format": "openai"},
}

# Populated at startup by ui_app.py via set_api_keys()
_api_keys: dict[str, str] = {}

# OpenRouter: show only free (zero-cost) models when fetching model list
_openrouter_free_only: bool = True

# OpenAI-compatible providers expose different context sizes, but Groq currently
# rejects output requests above 8,192 tokens for the models CARL exposes.  Keep
# this safety limit central so dynamically estimated analysis sizes cannot
# produce invalid requests.
_PROVIDER_MAX_OUTPUT_TOKENS = {"groq": 8192}
_GROQ_PROMPT_CHAR_BUDGET = 80_000
_COMPACTION_RETRY_BUDGETS = (32_000, 16_000, 8_000, 4_000, 2_000, 1_000)
_provider_cooldown_until: dict[str, float] = {}


def _safe_max_tokens(provider: str, requested: int | None) -> int:
    value = int(requested or 4096)
    value = max(1, value)
    limit = _PROVIDER_MAX_OUTPUT_TOKENS.get(provider)
    return min(value, limit) if limit else value


def _messages_char_count(messages: list) -> int:
    return sum(len(str(message.get("content", ""))) for message in messages)


def _next_compaction_budget(current_size: int) -> int | None:
    for budget in _COMPACTION_RETRY_BUDGETS:
        if budget < current_size:
            return budget
    return None


def _compact_text(text: str, budget: int) -> str:
    """Keep both ends of oversized evidence while making omission explicit."""
    text = str(text)
    if len(text) <= budget:
        return text
    if budget <= 40:
        return text[:max(0, budget)]
    omitted = len(text) - budget
    marker = f"\n...[{omitted:,} characters omitted to fit the model context]...\n"
    if len(marker) >= budget:
        return text[:budget]
    usable = max(0, budget - len(marker))
    head = int(usable * 0.65)
    tail = usable - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def _compact_messages(messages: list, max_chars: int) -> list:
    """Return an order-preserving, bounded copy of an OpenAI message list."""
    copied = [dict(message) for message in messages]
    total = _messages_char_count(copied)
    if total <= max_chars or total == 0:
        return copied

    budgets = [
        int(max_chars * len(str(m.get("content", ""))) / total)
        for m in copied
    ]
    remainder = max_chars - sum(budgets)
    for index in range(len(budgets) - 1, -1, -1):
        if remainder <= 0:
            break
        budgets[index] += 1
        remainder -= 1
    for message, budget in zip(copied, budgets):
        message["content"] = _compact_text(message.get("content", ""), budget)
    return copied


def _response_max_tokens_limit(response) -> int | None:
    """Extract a provider-advertised max_tokens ceiling from a 400 response."""
    try:
        detail = response.json()
    except Exception:
        detail = getattr(response, "text", "")
    text = str(detail)
    patterns = (
        r"maximum value for [`']?max_tokens[`']? is\s*(\d+)",
        r"[`']?max_tokens[`']?.{0,80}less than or equal to\s*[`']?(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def set_api_keys(keys: dict[str, str]) -> None:
    """Register provider API keys. Called by ui_app after loading settings."""
    global _api_keys
    _api_keys.update({k: v for k, v in keys.items() if v})


def set_openrouter_free_only(flag: bool) -> None:
    global _openrouter_free_only
    _openrouter_free_only = flag


# ── Hardcoded Anthropic model list (no public models endpoint) ────────────────
_ANTHROPIC_MODELS = [
    "anthropic/claude-opus-4-7",
    "anthropic/claude-sonnet-4-6",
    "anthropic/claude-haiku-4-5-20251001",
]

# OpenAI model prefixes worth showing (excludes embeddings, whisper, DALL-E, etc.)
_OPENAI_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")


def fetch_provider_models(provider: str, api_key: str) -> list[str]:
    """Fetch available model IDs for one provider, prefixed with provider/.
    Returns an empty list on any error."""
    import requests

    try:
        if provider == "groq":
            resp = requests.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            return sorted(f"groq/{m['id']}" for m in resp.json().get("data", []))

        elif provider == "openai":
            resp = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            ids = [m["id"] for m in resp.json().get("data", [])
                   if any(m["id"].startswith(p) for p in _OPENAI_PREFIXES)]
            return sorted(f"openai/{m}" for m in ids)

        elif provider == "anthropic":
            # No public endpoint — return curated list if key is present
            return list(_ANTHROPIC_MODELS)

        elif provider == "google":
            resp = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key},
                timeout=10,
            )
            resp.raise_for_status()
            models = []
            for m in resp.json().get("models", []):
                if "generateContent" in m.get("supportedGenerationMethods", []):
                    name = m["name"].replace("models/", "")
                    models.append(f"google/{name}")
            return sorted(models)

        elif provider == "huggingface":
            resp = requests.get(
                "https://router.huggingface.co/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            if resp.status_code == 200 and resp.content:
                try:
                    data  = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else data
                    models = sorted(
                        f"huggingface/{m['id']}"
                        for m in items
                        if isinstance(m, dict) and m.get("id")
                    )
                    if models:
                        return models
                except ValueError:
                    pass
            print(f"[huggingface] Could not retrieve model list "
                  f"(status {resp.status_code}) — type model names manually.")
            return []

        elif provider == "openrouter":
            resp = requests.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=15,
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
            if _openrouter_free_only:
                models = [m for m in models
                          if m.get("pricing", {}).get("prompt") == "0"
                          and m.get("pricing", {}).get("completion") == "0"]
            return sorted(f"openrouter/{m['id']}" for m in models if m.get("id"))

    except Exception as e:
        print(f"[{provider}] Could not fetch models: {e}")

    return []


def fetch_all_provider_models(api_keys: dict[str, str]) -> list[str]:
    """Query all providers that have a stored key. Returns a merged sorted list."""
    import concurrent.futures

    all_models: list[str] = []
    active = [(p, k) for p, k in api_keys.items() if k]
    if not active:
        return all_models

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(fetch_provider_models, p, k): p for p, k in active}
        for future in concurrent.futures.as_completed(futures):
            try:
                all_models.extend(future.result())
            except Exception as e:
                print(f"[fetch_all_provider_models] {e}")

    return sorted(all_models)


def _detect_provider(model_name: str) -> tuple[str, str]:
    """Return (provider, bare_model_name) from a (possibly prefixed) model string."""
    # Ollama: contains ":" and no "/"
    if ":" in model_name and "/" not in model_name:
        return "ollama", model_name
    # Explicit provider prefix
    for provider in _PROVIDERS:
        prefix = f"{provider}/"
        if model_name.startswith(prefix):
            return provider, model_name[len(prefix):]
    # No recognised prefix → legacy Groq default (backwards-compatible)
    return "groq", model_name


# ── OpenAI-compatible branch (Groq, OpenAI, HuggingFace) ─────────────────────

def _parse_openai_429(response) -> tuple[str, float]:
    try:
        body = response.json()
        msg = (body.get("error") or body).get("message", "")
    except Exception:
        return "unknown", 60

    if "tokens per day" in msg or "(TPD)" in msg:
        limit_type = "TPD"
    elif "tokens per minute" in msg or "(TPM)" in msg:
        limit_type = "TPM"
    elif "requests per minute" in msg or "(RPM)" in msg:
        limit_type = "RPM"
    else:
        limit_type = "unknown"

    retry_seconds = 60.0
    m = re.search(r"try again in ([^\.\n]+)", msg)
    if m:
        t = m.group(1).strip()
        total = 0.0
        for val, unit in re.findall(r"([\d.]+)\s*([hms])", t):
            v = float(val)
            if unit == "h":   total += v * 3600
            elif unit == "m": total += v * 60
            elif unit == "s": total += v
        if total > 0:
            retry_seconds = total
    return limit_type, retry_seconds


# Rate-limit retry policy: pause only for short, transient limits. If the API
# says the wait is longer than this, fail fast with a clear message instead of
# blocking the UI for minutes.
RETRY_MAX_WAIT = 8  # seconds


class RateLimitError(RuntimeError):
    """Raised when a rate/token limit can't be waited out. Its message is
    user-facing advice (how long, and to switch models) — callers surface it in
    the UI rather than treating it as a generic error."""


def _rate_limit_message(model: str, limit_type: str, retry_secs: float) -> str:
    if retry_secs >= 3600:
        wait_str = f"{retry_secs / 3600:.1f}h"
    elif retry_secs >= 60:
        wait_str = f"{retry_secs / 60:.0f}m"
    else:
        wait_str = f"{retry_secs:.0f}s"
    if limit_type == "TPD":
        return (f"Daily token limit reached for {model}. "
                f"Try again in ~{wait_str}, or switch to a different model.")
    return (f"Rate limit ({limit_type}) for {model} — needs ~{wait_str}. "
            f"Try again shortly, or switch to a different model.")


def _call_openai_compatible(base_url: str, api_key: str, provider: str,
                             model: str, messages: list, max_tokens: int,
                             temperature: float, status_fn=None,
                             cancel_fn=None) -> str:
    import requests
    result = None
    effective_max_tokens = _safe_max_tokens(provider, max_tokens)
    effective_messages = list(messages)
    if provider == "groq" and _messages_char_count(effective_messages) > _GROQ_PROMPT_CHAR_BUDGET:
        effective_messages = _compact_messages(
            effective_messages, _GROQ_PROMPT_CHAR_BUDGET)
        if status_fn:
            status_fn("Large input compacted automatically for the selected Groq model.")

    rate_limit_retries = 0
    for attempt in range(8):
        if cancel_fn and cancel_fn():
            return ""
        try:
            response = requests.post(
                base_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       model,
                    "messages":    effective_messages,
                    "max_tokens":  effective_max_tokens,
                    "temperature": temperature if temperature is not None else 0.2,
                },
                timeout=120,
            )
            if response.status_code == 400:
                advertised_limit = _response_max_tokens_limit(response)
                if (advertised_limit and advertised_limit < effective_max_tokens
                        and attempt < 7):
                    effective_max_tokens = max(1, advertised_limit)
                    if status_fn:
                        status_fn(
                            f"Model output limit detected; retrying with {effective_max_tokens} tokens.")
                    continue
                try:
                    detail = response.json()
                except Exception:
                    detail = response.text
                msg = f"[{provider}] Bad request (400): {detail}"
                print(msg)
                if status_fn:
                    status_fn(msg)
                break
            if response.status_code == 413:
                current_size = _messages_char_count(effective_messages)
                retry_budget = _next_compaction_budget(current_size)
                smaller = (_compact_messages(effective_messages, retry_budget)
                           if retry_budget else effective_messages)
                if attempt < 7 and _messages_char_count(smaller) < current_size:
                    effective_messages = smaller
                    msg = "Input exceeded the provider payload limit; retrying with a compact prompt."
                    print(f"[{provider}] {msg}")
                    if status_fn:
                        status_fn(msg)
                    continue
                msg = (f"[{provider}] The LLM pass could not fit the provider limit; "
                       "keeping CARL's deterministic output.")
                print(msg)
                if status_fn:
                    status_fn(msg)
                break
            if response.status_code == 404:
                msg = (f"[{provider}] Model '{model}' not found (404). "
                       f"It may not be available on the serverless inference endpoint.")
                print(msg)
                if status_fn:
                    status_fn(msg)
                break
            if response.status_code == 429:
                limit_type, retry_secs = _parse_openai_429(response)
                # Fail fast: only pause for a short, transient limit, and only on
                # the first attempt. Anything longer -> give up with a clear
                # message rather than blocking for minutes.
                if (limit_type == "TPD" or retry_secs > RETRY_MAX_WAIT
                        or rate_limit_retries >= 1):
                    raise RateLimitError(
                        _rate_limit_message(model, limit_type, retry_secs))
                # Short transient limit on the first attempt: one cancellable wait.
                rate_limit_retries += 1
                wait = int(retry_secs) + 1
                for remaining in range(wait, 0, -1):
                    if cancel_fn and cancel_fn():
                        if status_fn:
                            status_fn("Cancelled.")
                        return ""
                    msg = f"Rate limit ({limit_type}) — retrying in {remaining}s..."
                    print(f"\r[Rate limit] {msg}", end="", flush=True)
                    if status_fn:
                        status_fn(msg)
                    time.sleep(1)
                print()
                continue
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"].strip()
            break
        except RateLimitError:
            raise  # surfaced by the caller, not swallowed as a generic error
        except Exception as e:
            print(f"[{provider}] Error: {e}")
            break
    return result or ""


# ── Anthropic Messages API ────────────────────────────────────────────────────

def _call_anthropic(api_key: str, model: str, messages: list,
                    max_tokens: int, temperature: float, status_fn=None) -> str:
    import requests
    # Anthropic separates system prompt from the messages array
    system = ""
    user_messages = []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            user_messages.append(m)
    body = {
        "model":      model,
        "max_tokens": max_tokens or 4096,
        "messages":   user_messages,
    }
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json=body,
            timeout=120,
        )
        if response.status_code == 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            msg = f"[anthropic] Bad request (400): {detail}"
            print(msg)
            if status_fn:
                status_fn(msg)
            return ""
        response.raise_for_status()
        return response.json()["content"][0]["text"].strip()
    except Exception as e:
        msg = f"[anthropic] Error: {e}"
        print(msg)
        if status_fn:
            status_fn(msg)
        return ""


# ── Google Gemini API ─────────────────────────────────────────────────────────

def _call_google(api_key: str, model: str, messages: list,
                 max_tokens: int, temperature: float, status_fn=None) -> str:
    import requests
    # Convert OpenAI-style messages to Gemini format; system → user turn
    contents = []
    for m in messages:
        if m["role"] == "system":
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
        elif m["role"] == "assistant":
            contents.append({"role": "model", "parts": [{"text": m["content"]}]})
        else:
            contents.append({"role": "user", "parts": [{"text": m["content"]}]})
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": max_tokens or 4096,
                    "temperature":     temperature if temperature is not None else 0.2,
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        data       = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        # Skip thinking parts (gemini-2.5 thinking models)
        texts = [p.get("text", "") for p in parts if not p.get("thought", False)]
        return " ".join(texts).strip()
    except Exception as e:
        msg = f"[google] Error: {e}"
        print(msg)
        if status_fn:
            status_fn(msg)
        return ""


# ── Streaming callers ────────────────────────────────────────────────────────

def _stream_ollama(model: str, messages: list, config: LLMConfig,
                   cancel_fn=None):
    import json, requests
    if cancel_fn and cancel_fn():
        return
    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={"model": model, "messages": messages, "stream": True,
                  "options": config.to_options(), "keep_alive": KEEP_ALIVE},
            timeout=600, stream=True,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if cancel_fn and cancel_fn():
                response.close()
                return
            if line:
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break
    except Exception as e:
        print(f"[ollama stream] Error: {e}")
        raise


def _stream_openai_compatible(base_url: str, api_key: str, provider: str,
                               model: str, messages: list, config: LLMConfig,
                               status_fn=None, cancel_fn=None):
    import json, requests
    cooldown = _provider_cooldown_until.get(provider, 0.0) - time.time()
    if cooldown > 0:
        if status_fn:
            status_fn(_rate_limit_message(model, "unknown", cooldown))
        return
    effective_max_tokens = _safe_max_tokens(provider, config.num_predict)
    effective_messages = list(messages)
    if provider == "groq" and _messages_char_count(effective_messages) > _GROQ_PROMPT_CHAR_BUDGET:
        effective_messages = _compact_messages(
            effective_messages, _GROQ_PROMPT_CHAR_BUDGET)
    try:
        rate_limit_retries = 0
        for attempt in range(8):
            if cancel_fn and cancel_fn():
                if status_fn:
                    status_fn("Cancelled.")
                return
            response = requests.post(
                base_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": effective_messages,
                      "max_tokens": effective_max_tokens,
                      "temperature": config.temperature if config.temperature is not None else 0.2,
                      "stream": True},
                timeout=120, stream=True,
            )
            if response.status_code == 400:
                advertised_limit = _response_max_tokens_limit(response)
                if advertised_limit and advertised_limit < effective_max_tokens and attempt < 7:
                    effective_max_tokens = max(1, advertised_limit)
                    continue
            if response.status_code == 413:
                current_size = _messages_char_count(effective_messages)
                retry_budget = _next_compaction_budget(current_size)
                smaller = (_compact_messages(effective_messages, retry_budget)
                           if retry_budget else effective_messages)
                if attempt < 7 and _messages_char_count(smaller) < current_size:
                    effective_messages = smaller
                    print(f"[{provider} stream] Retrying with a compact prompt.")
                    continue
                print(
                    f"[{provider} stream] LLM payload could not be reduced further; "
                    "keeping raw CARL output.")
                return
            if response.status_code == 429:
                limit_type, retry_secs = _parse_openai_429(response)
                if (limit_type == "TPD" or retry_secs > RETRY_MAX_WAIT
                        or rate_limit_retries >= 1):
                    _provider_cooldown_until[provider] = time.time() + retry_secs
                    raise RateLimitError(
                        _rate_limit_message(model, limit_type, retry_secs))
                rate_limit_retries += 1
                wait = int(retry_secs) + 1
                print(f"[{provider} stream] Rate limited; retrying in {wait}s...")
                for remaining in range(wait, 0, -1):
                    if cancel_fn and cancel_fn():
                        if status_fn:
                            status_fn("Cancelled.")
                        return
                    if status_fn:
                        status_fn(f"Rate limit ({limit_type}) — retrying in {remaining}s...")
                    time.sleep(1)
                continue
            response.raise_for_status()
            for raw in response.iter_lines():
                if cancel_fn and cancel_fn():
                    response.close()
                    if status_fn:
                        status_fn("Cancelled.")
                    return
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    token = json.loads(data)["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except (ValueError, KeyError, IndexError):
                    pass
            break
    except RateLimitError:
        raise  # surfaced by the caller with its advice message
    except Exception as e:
        print(f"[{provider} stream] Error: {e}")
        raise


def _stream_anthropic(api_key: str, model: str, messages: list,
                      config: LLMConfig, cancel_fn=None):
    import json, requests
    if cancel_fn and cancel_fn():
        return
    system, user_messages = "", []
    for m in messages:
        if m["role"] == "system":
            system = m["content"]
        else:
            user_messages.append(m)
    body = {"model": model, "max_tokens": config.num_predict or 4096,
            "messages": user_messages, "stream": True}
    if system:
        body["system"] = system
    try:
        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body, timeout=120, stream=True,
        )
        response.raise_for_status()
        for raw in response.iter_lines():
            if cancel_fn and cancel_fn():
                response.close()
                return
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[6:])
                if chunk.get("type") == "content_block_delta":
                    text = chunk.get("delta", {}).get("text", "")
                    if text:
                        yield text
            except (ValueError, KeyError):
                pass
    except Exception as e:
        print(f"[anthropic stream] Error: {e}")
        raise


def _stream_google(api_key: str, model: str, messages: list,
                   config: LLMConfig, cancel_fn=None):
    import json, requests
    if cancel_fn and cancel_fn():
        return
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    try:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent",
            params={"key": api_key, "alt": "sse"},
            json={"contents": contents,
                  "generationConfig": {
                      "maxOutputTokens": config.num_predict or 4096,
                      "temperature": config.temperature if config.temperature is not None else 0.2,
                  }},
            timeout=120, stream=True,
        )
        response.raise_for_status()
        for raw in response.iter_lines():
            if cancel_fn and cancel_fn():
                response.close()
                return
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data: "):
                continue
            try:
                chunk = json.loads(line[6:])
                parts = chunk["candidates"][0]["content"]["parts"]
                for part in parts:
                    if not part.get("thought", False):
                        text = part.get("text", "")
                        if text:
                            yield text
            except (ValueError, KeyError, IndexError):
                pass
    except Exception as e:
        print(f"[google stream] Error: {e}")
        raise


def call_llm_stream(prompt: str, config: LLMConfig, messages: list | None = None,
                    status_fn=None, cancel_fn=None):
    """
    Generator yielding response tokens as they arrive.
    Supports Ollama, Groq, OpenAI, HuggingFace, Anthropic, Google.
    Falls back to a single yield of the complete response for unrecognised providers.
    """
    provider, bare_model = _detect_provider(config.model)
    msgs = messages if messages is not None else [{"role": "user", "content": prompt}]

    api_key = _api_keys.get(provider, "")
    if not api_key and provider == "groq":
        api_key = API_KEY or ""

    if provider == "ollama":
        yield from _stream_ollama(bare_model, msgs, config, cancel_fn=cancel_fn)
    elif provider in ("groq", "openai", "huggingface"):
        if not api_key:
            print(f"[WARNING] No API key for provider '{provider}'.")
            return
        yield from _stream_openai_compatible(
            _PROVIDERS[provider]["base_url"], api_key, provider, bare_model, msgs,
            config, status_fn=status_fn, cancel_fn=cancel_fn)
    elif provider == "anthropic":
        if not api_key:
            print(f"[WARNING] No API key for provider 'anthropic'.")
            return
        yield from _stream_anthropic(api_key, bare_model, msgs, config, cancel_fn=cancel_fn)
    elif provider == "google":
        if not api_key:
            print(f"[WARNING] No API key for provider 'google'.")
            return
        yield from _stream_google(api_key, bare_model, msgs, config, cancel_fn=cancel_fn)
    else:
        result = call_llm(prompt, config, messages=messages, status_fn=status_fn,
                          cancel_fn=cancel_fn)
        if result:
            yield result


# ── Unified caller ────────────────────────────────────────────────────────────

def call_llm(prompt: str, config: LLMConfig, use_chat: bool | None = None,
             status_fn=None, messages: list | None = None, cancel_fn=None) -> str:
    """
    Unified LLM caller supporting Ollama, Groq, OpenAI, HuggingFace,
    Anthropic, and Google Gemini.

    Pass `messages` (list of {role, content} dicts) for multi-turn chat;
    takes precedence over `prompt` for all cloud providers.
    """
    if use_chat is None:
        use_chat = getattr(config, "use_chat", False)

    provider, bare_model = _detect_provider(config.model)

    # ── Ollama (local) ────────────────────────────────────────────────────────
    if provider == "ollama":
        try:
            from ollama import generate, chat
            if use_chat:
                ollama_messages = messages if messages is not None else [
                    {"role": "system", "content":
                     "You are an accurate taxonomy assistant with expertise in "
                     "preparing taxonomic text for scientific publications."},
                    {"role": "user", "content": prompt},
                ]
                response = chat(
                    model=bare_model,
                    messages=ollama_messages,
                    options=config.to_options(),
                    keep_alive=KEEP_ALIVE,
                )
                return (response.get("message", {}).get("content", "") or "").strip()
            else:
                response = generate(
                    model=bare_model,
                    prompt=prompt,
                    options=config.to_options(),
                    keep_alive=KEEP_ALIVE,
                )
                return (response.get("response", "") or "").strip()
        except Exception as e:
            print(f"[ollama] Error: {e}")
            return ""

    # ── Cloud provider ────────────────────────────────────────────────────────
    api_key = _api_keys.get(provider, "")

    # Backwards-compatible fallback: use API_KEY for Groq if not yet migrated
    if not api_key and provider == "groq":
        api_key = API_KEY or ""

    if not api_key:
        print(f"[WARNING] No API key for provider '{provider}'. "
              f"Add it in Settings > LM Settings > API Keys.")
        return ""

    msgs = messages if messages is not None else [
        {"role": "user", "content": prompt}
    ]

    pinfo = _PROVIDERS[provider]
    fmt   = pinfo["format"]

    if fmt == "openai":
        url = pinfo["base_url"].format(model=bare_model)
        return _call_openai_compatible(
            url, api_key, provider, bare_model,
            msgs, config.num_predict, config.temperature, status_fn, cancel_fn,
        )
    elif fmt == "anthropic":
        return _call_anthropic(
            api_key, bare_model, msgs, config.num_predict, config.temperature, status_fn,
        )
    elif fmt == "google":
        return _call_google(
            api_key, bare_model, msgs, config.num_predict, config.temperature, status_fn,
        )
    return ""
