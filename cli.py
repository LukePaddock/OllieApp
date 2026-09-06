"""Textual TUI for chatting against a local llama-server (router mode) instance."""

import argparse
import os

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.suggester import Suggester
from textual.widgets import Footer, Header, Input, Markdown, Static

from file_handler import FileHandler
from ollie import OllieClient, PARAM_DESCRIPTIONS, split_think
from storage_handler import StorageHandler


class FileSuggester(Suggester):
    """Inline path completion for `/file <path>` (accept with -> or End)."""

    def __init__(self, file_handler):
        super().__init__(use_cache=False, case_sensitive=True)
        self.files = file_handler

    async def get_suggestion(self, value):
        if not value.startswith("/file "):
            return None
        arg = value[len("/file "):]
        directory, _, prefix = arg.rpartition("/")
        try:
            entries = self.files.list_dir(directory)
        except Exception:
            return None
        matches = sorted(e for e in entries if e.startswith(prefix)) if prefix else entries
        if not matches:
            return None
        completed = f"{directory}/{matches[0]}" if directory else matches[0]
        return f"/file {completed}"


class HistoryInput(Input):
    """An Input that recalls previously-submitted commands via up/down.

    In-memory only - the history doesn't persist across restarts, and it's
    not the saved conversation context (see /save), just a typing aid.
    """

    BINDINGS = [
        Binding("up", "history_prev", "Previous command", show=False),
        Binding("down", "history_next", "Next command", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history = []
        self._history_index = 0
        self._draft = ""

    def remember(self, text):
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_index = len(self._history)
        self._draft = ""

    def action_history_prev(self):
        if not self._history or self._history_index == 0:
            return
        if self._history_index == len(self._history):
            self._draft = self.value
        self._history_index -= 1
        self.value = self._history[self._history_index]
        self.cursor_position = len(self.value)

    def action_history_next(self):
        if self._history_index >= len(self._history):
            return
        self._history_index += 1
        self.value = self._draft if self._history_index == len(self._history) else self._history[self._history_index]
        self.cursor_position = len(self.value)


class ThinkingIndicator(Static):
    """A small animated "thinking..." placeholder, shown while reasoning is hidden."""

    FRAMES = ["thinking", "thinking.", "thinking..", "thinking..."]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, markup=False, **kwargs)
        self._frame = 0

    def on_mount(self):
        self.update(self.FRAMES[0])
        self.set_interval(0.4, self._tick)

    def _tick(self):
        self._frame = (self._frame + 1) % len(self.FRAMES)
        self.update(self.FRAMES[self._frame])


COMMANDS = """\
Commands:
  /bye                     quit
  /clear                   clear the current context
  /cls                     clear the screen (context is kept)
  /think <show|hide>       show reasoning text, or just a "thinking..." animation
  /models                  list models available on the server
  /model [name]            show/set the active model
  /prompt [text]           show/set the system prompt
  /loadp <file>            load a system prompt from prompts/
  /savep <file>            save the current system prompt to prompts/
  /param <key> <value>     set a sampling parameter (temperature, top_p, max_tokens, ...)
  /params                  list sampling parameters (set ones highlighted)
  /save <file>             save the current context to context/
  /load <file>             load a context from context/
  /contexts                list saved contexts
  /prompts                 list saved prompt files
  /file [path]             list a directory (default: pwd), or add a file's contents to context
  /slice <n>               drop the first n messages from context
  /undo                    remove the last message
  /print                   render the full context (with Markdown)
  /help                    show this message\
"""


def _coerce(value):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


class OllieApp(App):
    CSS = """
    #chat {
        padding: 0 1;
    }
    .thinking {
        color: $text-muted;
        text-style: italic;
    }
    .role-label {
        text-style: bold;
    }
    .queued {
        color: $text-muted;
    }
    .param-set {
        text-style: bold;
    }
    .param-unset {
        color: $text-muted;
    }
    """

    BINDINGS = [("ctrl+c", "quit", "Quit")]

    def __init__(self, base_url, api_key, model, system_prompt_file):
        super().__init__()
        self.client = OllieClient(base_url=base_url, api_key=api_key, model=model)
        self.storage = StorageHandler()
        self.files = FileHandler()
        self._system_prompt_file = system_prompt_file
        self._awaiting_model_choice = False
        self._model_choices = []
        self._chat_busy = False
        self._chat_queue = []
        self._show_thinking = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="chat")
        yield HistoryInput(
            placeholder="Type a message or /help",
            id="input",
            suggester=FileSuggester(self.files),
        )
        yield Footer()

    def on_mount(self):
        self.query_one("#input", Input).focus()

        if self._system_prompt_file:
            self.client.set_system_prompt(self.storage.load_prompt(self._system_prompt_file))

        if self.client.model is None:
            self._prompt_model_choice()
        else:
            self._log(f"Using model: {self.client.model}")
            self._log("Type /help for commands, or just start chatting.")

    def _prompt_model_choice(self):
        try:
            models = self.client.list_models()
        except Exception as e:
            self._log(f"Could not reach the server: {e}")
            return
        if not models:
            self._log("No models available from the server.")
            return
        self._model_choices = models
        self._awaiting_model_choice = True
        lines = ["Available models:"] + [f"  {i}: {m}" for i, m in enumerate(models)]
        lines.append("Enter a number to select a model.")
        self._log("\n".join(lines))

    def _log(self, text, classes=""):
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(Static(text, markup=False, classes=classes))
        chat.scroll_end(animate=False)

    def on_input_submitted(self, event: Input.Submitted):
        text = event.value
        event.input.value = ""
        if not text:
            return

        if self._awaiting_model_choice:
            self._handle_model_choice(text)
            return

        if text.startswith("/"):
            event.input.remember(text)
            self._handle_command(text[1:])
            return

        self._log(f"> {text}")
        if self._chat_busy:
            self._chat_queue.append(text)
            self._log(f"(queued — {len(self._chat_queue)} waiting)", classes="queued")
        else:
            self._start_chat(text)

    def _handle_model_choice(self, text):
        try:
            model = self._model_choices[int(text)]
        except (ValueError, IndexError):
            self._log("Not a valid selection.")
            return
        self.client.set_model(model)
        self._awaiting_model_choice = False
        self._log(f"Using model: {model}")
        self._log("Type /help for commands, or just start chatting.")

    def _start_chat(self, text):
        self._chat_busy = True
        chat = self.query_one("#chat", VerticalScroll)
        if self._show_thinking:
            thinking = Static("", markup=False, classes="thinking")
        else:
            thinking = ThinkingIndicator(classes="thinking")
        response = Markdown()
        chat.mount(thinking)
        chat.mount(response)
        chat.scroll_end(animate=False)
        self._run_chat(text, thinking, response, chat, self._show_thinking)

    @work(thread=True, exclusive=True)
    def _run_chat(self, text, thinking_widget, response_widget, chat, show_thinking):
        thinking_buffer = ""
        thinking_removed = False
        stream = None

        def remove_thinking():
            nonlocal thinking_removed
            if not thinking_removed:
                thinking_removed = True
                self.call_from_thread(thinking_widget.remove)

        try:
            for kind, piece in self.client.chat(text):
                if kind == "think":
                    if show_thinking:
                        thinking_buffer += piece
                        self.call_from_thread(thinking_widget.update, "thinking:\n" + thinking_buffer)
                else:
                    if not show_thinking:
                        remove_thinking()
                    if stream is None:
                        stream = self.call_from_thread(Markdown.get_stream, response_widget)
                    self.call_from_thread(stream.write, piece)
                self.call_from_thread(chat.scroll_end, animate=False)
        except Exception as e:
            if not show_thinking:
                remove_thinking()
            self.call_from_thread(response_widget.update, f"Error: {e}")
        finally:
            if stream is not None:
                self.call_from_thread(stream.stop)
            if not show_thinking:
                remove_thinking()
            self.call_from_thread(self._chat_finished)

    def _chat_finished(self):
        self._chat_busy = False
        if self._chat_queue:
            self._start_chat(self._chat_queue.pop(0))

    def _show_params(self):
        chat = self.query_one("#chat", VerticalScroll)
        set_params = self.client.get_params()
        names = sorted(set(PARAM_DESCRIPTIONS) | set(set_params))

        for name in names:
            desc = PARAM_DESCRIPTIONS.get(name, "(undocumented)")
            if name in set_params:
                text = f"{name} = {set_params[name]}    -- {desc}"
                chat.mount(Static(text, markup=False, classes="param-set"))
            else:
                text = f"{name}    -- {desc}"
                chat.mount(Static(text, markup=False, classes="param-unset"))

        chat.scroll_end(animate=False)

    def _print_context(self):
        chat = self.query_one("#chat", VerticalScroll)
        client = self.client

        if client.system_prompt:
            self._mount_message(chat, "system", client.system_prompt)
        for message in client.messages:
            self._mount_message(chat, message["role"], message["content"])

        chat.scroll_end(animate=False)

    def _mount_message(self, chat, role, content):
        chat.mount(Static(f"{role}:", markup=False, classes="role-label"))
        thinking, answer = split_think(content)
        if thinking:
            chat.mount(Static("thinking:\n" + thinking, markup=False, classes="thinking"))
        if answer:
            chat.mount(Markdown(answer))

    def _handle_file(self, param):
        try:
            full = self.files.resolve(param)
        except Exception as e:
            self._log(f"Error: {e}")
            return

        if not param or os.path.isdir(full):
            try:
                entries = self.files.list_dir(param)
            except Exception as e:
                self._log(f"Error: {e}")
                return
            self._log(f"{full}:\n" + ("\n".join(entries) if entries else "(empty)"))
            return

        try:
            full_path, content = self.files.read_file(param)
        except Exception as e:
            self._log(f"Error: {e}")
            return

        ext = os.path.splitext(full_path)[1].lstrip(".")
        formatted = f"file: {full_path}\n```{ext}\n{content}\n```"
        self.client.add_to_context([{"role": "user", "content": formatted}])

        chat = self.query_one("#chat", VerticalScroll)
        self._mount_message(chat, "user", formatted)
        chat.scroll_end(animate=False)

    def _handle_command(self, raw):
        parts = raw.split(" ", 1)
        command = parts[0]
        param = parts[1].strip() if len(parts) > 1 else ""
        client = self.client
        storage = self.storage

        if command in ("bye", "quit", "exit"):
            self.exit()

        elif command == "help":
            self._log(COMMANDS)

        elif command == "clear":
            client.clear_context()
            self._log("Context cleared.")

        elif command == "cls":
            self.query_one("#chat", VerticalScroll).remove_children()

        elif command == "think":
            if param in ("show", "on"):
                self._show_thinking = True
                self._log("Reasoning display: show")
            elif param in ("hide", "off"):
                self._show_thinking = False
                self._log("Reasoning display: hide")
            elif not param:
                self._log(f"Reasoning display: {'show' if self._show_thinking else 'hide'}")
            else:
                self._log("Usage: /think <show|hide>")

        elif command == "models":
            try:
                self._log("\n".join(client.list_models()))
            except Exception as e:
                self._log(f"Error: {e}")

        elif command == "model":
            if not param:
                self._log(f"Current model: {client.model}")
            else:
                client.set_model(param)
                self._log(f"Model set to: {param}")

        elif command == "prompt":
            if not param:
                self._log(client.system_prompt or "(no system prompt set)")
            else:
                client.set_system_prompt(param)
                self._log("System prompt updated.")

        elif command == "loadp":
            if not param:
                self._log("Usage: /loadp <file>")
            else:
                try:
                    client.set_system_prompt(storage.load_prompt(param))
                    self._log(f"Loaded system prompt from {param}")
                except FileNotFoundError as e:
                    self._log(str(e))

        elif command == "savep":
            if not param:
                self._log("Usage: /savep <file>")
            else:
                storage.save_prompt(param, client.system_prompt)
                self._log(f"Saved system prompt to {param}")

        elif command == "param":
            try:
                key, value = param.split(" ", 1)
            except ValueError:
                self._log("Usage: /param <key> <value>")
            else:
                client.set_param(key, _coerce(value))
                self._log(f"{key} = {client.params[key]}")

        elif command == "params":
            self._show_params()

        elif command == "save":
            if not param:
                self._log("Usage: /save <file>")
            else:
                storage.save_context(param, client.messages, client.system_prompt, client.model, client.get_params())
                self._log(f"Saved context to {param}")

        elif command == "load":
            if not param:
                self._log("Usage: /load <file>")
            else:
                try:
                    data = storage.load_context(param)
                except FileNotFoundError as e:
                    self._log(str(e))
                else:
                    client.messages = data["messages"]
                    client.system_prompt = data["system_prompt"]
                    if data["model"]:
                        client.model = data["model"]
                    if data["params"]:
                        client.params.update(data["params"])
                    self._log(f"Loaded context from {param}")

        elif command == "contexts":
            self._log("\n".join(storage.list_contexts()) or "(none)")

        elif command == "prompts":
            self._log("\n".join(storage.list_prompts()) or "(none)")

        elif command == "file":
            self._handle_file(param)

        elif command == "slice":
            try:
                client.slice_context(int(param))
            except ValueError:
                self._log("Usage: /slice <n>")

        elif command == "undo":
            client.undo_last()
            self._log("Removed last message.")

        elif command == "print":
            self._print_context()

        else:
            self._log(COMMANDS)


def main():
    parser = argparse.ArgumentParser(description="Terminal chat client for a local llama-server")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    parser.add_argument("--api-key", default="not-needed")
    parser.add_argument("--model", default=None, help="Model id to use (skip the picker)")
    parser.add_argument("--system-prompt-file", default=None, help="Prompt file (from prompts/) to load at startup")
    args = parser.parse_args()

    app = OllieApp(args.base_url, args.api_key, args.model, args.system_prompt_file)
    app.run()


if __name__ == "__main__":
    main()
