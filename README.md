# ollie

A terminal-based AI chat client for a local `llama-server` instance, talked to
via the OpenAI-compatible API (the `openai` Python library).

It's built around `llama-server` running in **router mode** (`--models-preset
presets.ini`), so the client can list whatever models the router has
configured and switch between them per-request — no reloading or restarting
the server.

## Requirements

- Python >= 3.9
- A running `llama-server` in router mode, reachable over HTTP

## Install

```
pip install -e .
```

This installs the `ollie` command via `pyproject.toml`.

## Usage

```
ollie --base-url http://10.0.0.25:11434/v1
```

If `--model` isn't given, `ollie` fetches the list of models from the
server's `/models` endpoint and prompts you to pick one.

Flags:

| Flag | Default | Description |
|---|---|---|
| `--base-url` | `http://10.0.0.25:11434/v1` | OpenAI-compatible endpoint of your `llama-server` router |
| `--api-key` | `not-needed` | Sent as the API key; `llama-server` doesn't check it by default |
| `--model` | *(prompts to choose)* | Model id to use, skipping the picker |
| `--system-prompt-file` | *(none)* | Load a saved prompt from `prompts/` at startup |

Anything typed that doesn't start with `/` is sent as a chat message and
streamed back token by token, including model reasoning — if the server
sends a separate `reasoning_content`/`reasoning` stream, it's shown (and
saved) inline as a `<think>...</think>` block.

## Commands

Typed at the `-->` prompt, prefixed with `/`:

| Command | Description |
|---|---|
| `/bye` | quit |
| `/clear` | clear the current context |
| `/models` | list models available from the server |
| `/model [name]` | show, or switch, the active model |
| `/prompt [text]` | show, or set, the system prompt |
| `/loadp <file>` | load a system prompt from `prompts/` |
| `/savep <file>` | save the current system prompt to `prompts/` |
| `/param <key> <value>` | set a sampling parameter (`temperature`, `top_p`, `max_tokens`, ...) |
| `/params` | show current sampling parameters |
| `/save <file>` | save the current context to `context/` |
| `/load <file>` | load a context from `context/` |
| `/contexts` | list saved contexts |
| `/prompts` | list saved prompt files |
| `/slice <n>` | drop the first `n` messages from context |
| `/undo` | remove the last message |
| `/print` | print the full context as text |
| `/help` | show the command list |

## Storage

`prompts/` and `context/` are plain, human-readable/editable text files —
nothing is written to a database, and nothing is saved automatically. Only
`/save` and `/savep` write to disk.

A saved context looks like:

```
::model:: qwen3-4b
::params:: {"temperature": 0.7}
::system::
be helpful
::user::
hello
::assistant::
<think>
reasoning here
</think>
final answer
```

There's no automatic conversation history — only what you explicitly `/save`
is kept.

## Project layout

- `ollie.py` — `OllieClient`, the OpenAI wrapper: holds the model, system
  prompt, sampling params, and message list; streams chat responses.
- `storage_handler.py` — `StorageHandler`: reads/writes prompt and context
  files under `prompts/` and `context/`.
- `cli.py` — the REPL and command parser; installed as the `ollie` entry
  point.
