"""Thin wrapper around the OpenAI client for talking to a local llama-server instance."""

from openai import OpenAI


class OllieClient:
    DEFAULT_PARAMS = {
        "temperature": 0.8,
        "top_p": 0.95,
        "max_tokens": 4096,
    }

    def __init__(self, base_url="http://10.0.0.25:8080/v1", api_key="not-needed",
                 model=None, system_prompt="", **params):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.params = {**self.DEFAULT_PARAMS, **params}
        self.messages = []

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
        """Send `prompt`, streaming back text chunks (including <think> reasoning)."""
        if self.model is None:
            raise RuntimeError("No model set - call set_model() first")

        if prompt:
            self.messages.append({"role": "user", "content": prompt})

        request_messages = self.messages
        if self.system_prompt:
            request_messages = [{"role": "system", "content": self.system_prompt}] + self.messages

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=request_messages,
            stream=True,
            **self.params,
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
                    yield "<think>\n"
                content += reasoning
                yield reasoning
            if delta.content:
                if thinking:
                    thinking = False
                    content += "\n</think>\n"
                    yield "\n</think>\n"
                content += delta.content
                yield delta.content

        self.messages.append({"role": "assistant", "content": content})
