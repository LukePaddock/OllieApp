"""Thin wrapper around the OpenAI client for talking to a local llama-server instance."""

import inspect
import re

from openai import OpenAI

_THINK_RE = re.compile(r"^<think>\n(.*?)\n</think>\n?", re.DOTALL)


def split_think(content):
    """Split message content into (thinking, answer) text.

    Assistant messages store reasoning as a leading `<think>...</think>` block
    (see `OllieClient.chat`); this pulls it back apart for display.
    """
    match = _THINK_RE.match(content)
    if not match:
        return "", content
    return match.group(1), content[match.end():]


PARAM_DESCRIPTIONS = {
    "temperature": "randomness of sampling; higher = more varied, lower = more deterministic",
    "top_p": "nucleus sampling; only consider tokens in the top p probability mass",
    "top_k": "only consider the k most likely tokens",
    "min_p": "drop tokens below this probability relative to the top token",
    "max_tokens": "maximum number of tokens to generate in the response",
    "presence_penalty": "penalize tokens that have appeared at all so far, to encourage new topics",
    "frequency_penalty": "penalize tokens proportional to how often they've appeared, to reduce repetition",
    "repeat_penalty": "penalty applied to recently generated tokens to reduce repetition (llama.cpp)",
    "repeat_last_n": "number of recent tokens considered for repeat_penalty (llama.cpp)",
    "seed": "fixed random seed for reproducible output",
    "stop": "string(s) that stop generation early when produced",
    "mirostat": "enable Mirostat sampling: 0=off, 1=v1, 2=v2 (llama.cpp)",
    "mirostat_tau": "Mirostat target entropy/perplexity (llama.cpp)",
    "mirostat_eta": "Mirostat learning rate (llama.cpp)",
    "grammar": "GBNF grammar the output must conform to (llama.cpp)",
    "json_schema": "JSON schema the output must conform to (llama.cpp)",
    "dry_multiplier": "DRY repetition penalty strength (llama.cpp)",
    "dry_base": "DRY repetition penalty base (llama.cpp)",
    "dry_allowed_length": "longest repeated sequence allowed before the DRY penalty kicks in (llama.cpp)",
    "xtc_probability": "probability of applying XTC sampling to remove top tokens (llama.cpp)",
    "xtc_threshold": "probability threshold for XTC token removal (llama.cpp)",
}
"""Short descriptions for /params output. Anything not listed here is still a
valid param (see OllieClient.chat) - just undocumented in this table."""


class OllieClient:
    def __init__(self, base_url="http://localhost:8080/v1", api_key="not-needed",
                 model=None, system_prompt="", **params):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        # Nothing is sent unless explicitly set (via a kwarg here or set_param) -
        # the server's own defaults apply to anything left unset.
        self.params = dict(params)
        self.messages = []
        self._create_param_names = set(
            inspect.signature(self.client.chat.completions.create).parameters
        ) - {"self"}

    # -- server / model introspection ------------------------------------

    def list_models(self):
        return [m.id for m in self.client.models.list().data]

    def set_model(self, model_id):
        self.model = model_id

    # -- config -----------------------------------------------------------

    def set_system_prompt(self, text):
        self.system_prompt = text

    def set_param(self, key, value):
        self.params[key] = value

    def get_params(self):
        return dict(self.params)

    # -- context management -------------------------------------------------

    def clear_context(self):
        self.messages = []

    def slice_context(self, n):
        self.messages = self.messages[n:]

    def undo_last(self):
        if self.messages:
            self.messages.pop()

    def add_to_context(self, messages):
        self.messages += messages

    def get_context_as_string(self):
        parts = []
        if self.system_prompt:
            parts.append(f"system:\n  {self.system_prompt}\n")
        for message in self.messages:
            parts.append(f"{message['role']}:\n  {message['content']}\n")
        return "\n".join(parts)

    # -- chat ---------------------------------------------------------------

    def chat(self, prompt):
        """Send `prompt`, streaming back (kind, text) pairs.

        `kind` is "think" for reasoning chunks and "content" for the final answer,
        so callers can render/route them differently. The saved message still
        combines both, wrapped as `<think>...</think>` around the reasoning.
        """
        if self.model is None:
            raise RuntimeError("No model set - call set_model() first")

        if prompt:
            self.messages.append({"role": "user", "content": prompt})

        request_messages = self.messages
        if self.system_prompt:
            request_messages = [{"role": "system", "content": self.system_prompt}] + self.messages

        known_params = {k: v for k, v in self.params.items() if k in self._create_param_names}
        extra_params = {k: v for k, v in self.params.items() if k not in self._create_param_names}

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=request_messages,
            stream=True,
            extra_body=extra_params,
            **known_params,
        )

        content = ""
        thinking = False
        for chunk in stream:
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                if not thinking:
                    thinking = True
                    content += "<think>\n"
                content += reasoning
                yield "think", reasoning
            if delta.content:
                if thinking:
                    thinking = False
                    content += "\n</think>\n"
                content += delta.content
                yield "content", delta.content

        self.messages.append({"role": "assistant", "content": content})
