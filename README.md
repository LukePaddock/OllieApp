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

Ollie is a [Textual](https://textual.textualize.io/) TUI: a scrollable chat
log above a persistent input box. Anything typed that doesn't start with `/`
is sent as a chat message and streamed back live. The final answer renders
as proper Markdown (headers, lists, bold/italic, code blocks, tables, ...).

If the server sends a separate `reasoning_content`/`reasoning` stream, by
default it's hidden — you just see a "thinking..." animation until the real
answer starts. `/think show` switches to showing the reasoning live, in a
dimmed line above the answer; `/think hide` (the default) goes back to just
the animation; `/think` with no argument reports which mode you're in.
Either way, what gets saved to `context/` is the full text with reasoning
wrapped in a `<think>...</think>` block, as described below — hiding it in
the UI doesn't drop it from what's saved.

Up/down arrow in the input box recalls previously-typed `/commands` (not
chat messages, and not persisted across restarts) — a quick way to get back
to a `/save`, `/load`, or `/param` you typed a minute ago.

## Commands

Typed at the input box, prefixed with `/`:

| Command | Description |
|---|---|
| `/bye` | quit |
| `/clear` | clear the current context |
| `/think <show\|hide>` | show reasoning live, or just a "thinking..." animation (default: hide) |
| `/models` | list models available from the server |
| `/model [name]` | show, or switch, the active model |
| `/prompt [text]` | show, or set, the system prompt |
| `/loadp <file>` | load a system prompt from `prompts/` |
| `/savep <file>` | save the current system prompt to `prompts/` |
| `/param <key> <value>` | set a sampling parameter — anything the server accepts (`temperature`, `top_k`, `min_p`, `repeat_penalty`, ...), not just `temperature`/`top_p`/`max_tokens` |
| `/params` | list known sampling parameters with descriptions; ones you've set are highlighted |
| `/save <file>` | save the current context to `context/` |
| `/load <file>` | load a context from `context/` |
| `/contexts` | list saved contexts |
| `/prompts` | list saved prompt files |
| `/file [path]` | list a directory (default: pwd), or add a file's contents to context |
| `/slice <n>` | drop the first `n` messages from context |
| `/undo` | remove the last message |
| `/print` | render the full context, same as live chat (Markdown answers, reasoning shown separately) |
| `/cls` | clear the screen (context is kept — `/print` brings it back) |
| `/help` | show the command list |

`/file` works with relative paths (resolved against wherever you launched
`ollie` from), absolute paths, and `~`. Point it at a directory to list what's
there; point it at a file to read it in as a user message (wrapped in a
Markdown code fence with the file's path as a header). It refuses files over
256KB or that aren't valid UTF-8 text, and it never recurses into a directory
automatically — you add files one at a time, so you always know what's going
into context (and how many tokens it's costing you). While typing a
`/file <path>`, press → or End to accept an inline autocomplete suggestion
for the next path segment.

Ollie doesn't send any sampling parameter to the server unless you've set it
with `/param` — whatever you leave unset just falls back to the server's own
default. `/params` lists every parameter Ollie knows about, with a
description; ones you've actually set are shown with their value and
highlighted, so you can tell "configured by me" apart from "using the
server's default."

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
- `file_handler.py` — `FileHandler`: read-only browsing of arbitrary
  filesystem paths for `/file`, separate from `storage_handler.py` since it
  isn't limited to ollie's own managed directories.
- `cli.py` — the Textual TUI and command parser; installed as the `ollie`
  entry point.
