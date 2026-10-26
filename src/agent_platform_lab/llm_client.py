"""Shared LLM client: create one provider client per process and expose a single execute() method."""

import os
from types import SimpleNamespace


# Create Client and return, provide execute method
class ClientSingleton:
    _instance = None
    _client = None
    _provider = 'groq'  # 'groq' | 'anthropic' | 'ollama' | 'openrouter'
    _model = "openai/gpt-oss-120b"
    # For _provider = 'ollama', set _model to whatever you've pulled, e.g.
    # "qwen2.5-coder:7b" — run `ollama pull qwen2.5-coder:7b` first, and
    # make sure the Ollama app/server is running (localhost:11434).
    # For _provider = 'openrouter', _model must be one of OpenRouter's own
    # "<provider>/<model>" IDs from https://openrouter.ai/models.
    # For _provider = 'anthropic', _model must be a Claude model ID such as
    # "claude-opus-5-5".

    # Cumulative token usage across every execute() call since the last
    # reset_usage(). The worker reports it so real token spend is visible
    # next to the mock per-tool costs.
    _usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    @classmethod
    def configure(cls, provider: str, model: str) -> None:
        """Select provider and model; drops any existing client so the next call builds a new one."""
        if provider not in ('groq', 'ollama', 'openrouter', 'anthropic'):
            raise ValueError("Invalid client name. Valid client names are groq, ollama, openrouter, and anthropic")
        cls._provider = provider
        cls._model = model
        cls._instance = None
        cls._client = None

    @classmethod
    def get_llm_client(cls):
        if cls._instance is None:
            cls._instance = cls()
            # This is where the client is initialized once.
            # A request whose TCP connection dies mid-flight (e.g. the
            # machine sleeps) otherwise hangs forever with no timeout, so
            # every SDK gets `timeout` (seconds) at construction.
            # SDKs are imported per provider so only the one in use must be installed.
            if cls._provider == 'groq':
                from groq import Groq

                my_api_key = os.environ.get('GROQ_API_KEY_2')
                cls._client = Groq(api_key=my_api_key, timeout=120.0)
            elif cls._provider == 'ollama':
                # Ollama exposes an OpenAI-compatible endpoint on localhost —
                # no API key, no rate limit, runs entirely on your own GPU.
                # Uses the real `openai` SDK (not Groq's) because Groq's SDK
                # hardcodes its request path as "/openai/v1/chat/completions",
                # which produces a wrong URL with a custom base_url.
                from openai import OpenAI

                cls._client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1", timeout=120.0)
            elif cls._provider == 'openrouter':
                # Same reason as 'ollama': OpenRouter exposes a standard
                # OpenAI-compatible /chat/completions endpoint.
                from openai import OpenAI

                my_api_key = os.environ.get('OPENROUTER_API_KEY')
                cls._client = OpenAI(api_key=my_api_key, base_url="https://openrouter.ai/api/v1", timeout=120.0)
            elif cls._provider == 'anthropic':
                from anthropic import Anthropic

                my_api_key = os.environ.get('ANTHROPIC_API_KEY')
                cls._client = Anthropic(api_key=my_api_key, timeout=120.0)
            else:
                cls._instance = None
                raise ValueError("Invalid client name. Valid client names are groq, ollama, openrouter, and anthropic")

        return cls._client

    @classmethod
    def execute(cls, messages, max_tokens=2000, temperature=0.5):
        cls.get_llm_client()
        if cls._provider == 'anthropic':
            # Anthropic takes the system prompt as a separate parameter, not a
            # "system" message, and current Claude models reject `temperature`.
            system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
            response = cls._client.messages.create(
                model=cls._model,
                max_tokens=max_tokens,
                system=system,
                messages=[m for m in messages if m["role"] != "system"],
            )
            usage = getattr(response, "usage", None)
            if usage is not None:
                prompt_tokens = getattr(usage, "input_tokens", 0) or 0
                completion_tokens = getattr(usage, "output_tokens", 0) or 0
                cls._record_usage(prompt_tokens, completion_tokens)
            # Callers expect `.content` to be a plain string (what the
            # OpenAI-style `.message` gives them below). Anthropic returns a
            # list of blocks, which can include thinking blocks, so join the
            # text blocks rather than assuming content[0] is text.
            text = "".join(block.text for block in response.content if block.type == "text")
            return SimpleNamespace(content=text)

        response = cls._client.chat.completions.create(
            model=cls._model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=messages
        )
        usage = getattr(response, "usage", None)
        if usage is not None:
            cls._record_usage(
                getattr(usage, "prompt_tokens", 0) or 0,
                getattr(usage, "completion_tokens", 0) or 0,
            )
        return response.choices[0].message

    @classmethod
    def _record_usage(cls, prompt_tokens: int, completion_tokens: int) -> None:
        cls._usage["prompt_tokens"] += prompt_tokens
        cls._usage["completion_tokens"] += completion_tokens
        cls._usage["total_tokens"] += prompt_tokens + completion_tokens

    @classmethod
    def get_usage(cls) -> dict:
        """Cumulative token usage since the last reset_usage()."""
        return dict(cls._usage)

    @classmethod
    def reset_usage(cls) -> None:
        cls._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
