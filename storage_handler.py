"""Human-readable text-file storage for prompts and saved conversation contexts."""

import json
import re
from pathlib import Path

_ROLE_MARKER = re.compile(r"^::(system|user|assistant)::$")
_META_MARKER = re.compile(r"^::(model|params)::\s?(.*)$")


class StorageHandler:
    def __init__(self, base_dir=".", prompts_dir="prompts", context_dir="context"):
        self.dir_prompts = Path(base_dir) / prompts_dir
        self.dir_context = Path(base_dir) / context_dir
        self.dir_prompts.mkdir(parents=True, exist_ok=True)
        self.dir_context.mkdir(parents=True, exist_ok=True)

    # -- prompts --------------------------------------------------------------

    def save_prompt(self, name, text):
        (self.dir_prompts / name).write_text(text, encoding="utf-8")

    def load_prompt(self, name):
        path = self.dir_prompts / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found: {path}")
        return path.read_text(encoding="utf-8")

    def list_prompts(self):
        return sorted(p.name for p in self.dir_prompts.iterdir() if p.is_file())

    # -- contexts ---------------------------------------------------------------

    def save_context(self, name, messages, system_prompt="", model=None, params=None):
        lines = []
        if model:
            lines.append(f"::model:: {model}")
        if params:
            lines.append(f"::params:: {json.dumps(params)}")
        if system_prompt:
            lines.append("::system::")
            lines.append(system_prompt)
        for message in messages:
            lines.append(f"::{message['role']}::")
            lines.append(message["content"])
        (self.dir_context / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def load_context(self, name):
        path = self.dir_context / name
        if not path.exists():
            raise FileNotFoundError(f"Context file not found: {path}")

        system_prompt = ""
        model = None
        params = {}
        messages = []

        role = None
        buffer = []

        def flush():
            nonlocal buffer, role, system_prompt
            if role is None:
                return
            text = "\n".join(buffer).strip("\n")
            if role == "system":
                system_prompt = text
            else:
                messages.append({"role": role, "content": text})
            buffer = []

        for line in path.read_text(encoding="utf-8").splitlines():
            role_match = _ROLE_MARKER.match(line)
            if role_match:
                flush()
                role = role_match.group(1)
                continue

            meta_match = _META_MARKER.match(line) if role is None else None
            if meta_match:
                key, value = meta_match.groups()
                if key == "model":
                    model = value.strip()
                elif key == "params":
                    params = json.loads(value)
                continue

            buffer.append(line)
        flush()

        return {
            "system_prompt": system_prompt,
            "model": model,
            "params": params,
            "messages": messages,
        }

    def list_contexts(self):
        return sorted(p.name for p in self.dir_context.iterdir() if p.is_file())
