"""Terminal REPL for chatting against a local llama-server (router mode) instance."""

import argparse
import sys

from ollie import OllieClient
from storage_handler import StorageHandler

COMMANDS = """
Commands:
  /bye                     quit
  /clear                   clear the current context
  /models                  list models available on the server
  /model [name]            show/set the active model
  /prompt [text]           show/set the system prompt
  /loadp <file>            load a system prompt from prompts/
  /savep <file>            save the current system prompt to prompts/
  /param <key> <value>     set a sampling parameter (temperature, top_p, max_tokens, ...)
  /params                  show current sampling parameters
  /save <file>             save the current context to context/
  /load <file>             load a context from context/
  /contexts                list saved contexts
  /prompts                 list saved prompt files
  /slice <n>               drop the first n messages from context
  /undo                    remove the last message
  /print                   print the full context as text
  /help                    show this message
"""


def main():
    parser = argparse.ArgumentParser(description="Terminal chat client for a local llama-server")
    parser.add_argument("--base-url", default="http://10.0.0.25:11434/v1")
    parser.add_argument("--api-key", default="not-needed")
    parser.add_argument("--model", default=None, help="Model id to use (skip the picker)")
    parser.add_argument("--system-prompt-file", default=None, help="Prompt file (from prompts/) to load at startup")
    args = parser.parse_args()

    client = OllieClient(base_url=args.base_url, api_key=args.api_key, model=args.model)
    storage = StorageHandler()

    if args.system_prompt_file:
        client.set_system_prompt(storage.load_prompt(args.system_prompt_file))

    if client.model is None:
        try:
            models = client.list_models()
        except Exception as e:
            print(f"Could not reach the server at {args.base_url}: {e}")
            sys.exit(1)
        if not models:
            print("No models available from the server.")
            sys.exit(1)
        client.set_model(_choose_model(models))

    print(f"Using model: {client.model}")
    print("Type /help for commands, or just start chatting.")

    running = True
    while running:
        try:
            user_input = input("\n--> ")
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if user_input.startswith("/"):
            running = _handle_command(user_input[1:], client, storage)
            continue

        try:
            for chunk in client.chat(user_input):
                print(chunk, end="", flush=True)
            print()
        except Exception as e:
            print(f"\nError: {e}")


def _choose_model(models):
    print("Available models:")
    for i, m in enumerate(models):
        print(f"  {i}: {m}")
    while True:
        try:
            selection = input("Select a model: ")
            return models[int(selection)]
        except (ValueError, IndexError):
            print("Not a valid selection.")


def _coerce(value):
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def _handle_command(raw, client, storage):
    parts = raw.split(" ", 1)
    command = parts[0]
    param = parts[1].strip() if len(parts) > 1 else ""

    if command in ("bye", "quit", "exit"):
        return False

    elif command == "help":
        print(COMMANDS)

    elif command == "clear":
        client.clear_context()
        print("Context cleared.")

    elif command == "models":
        for m in client.list_models():
            print(f"  {m}")

    elif command == "model":
        if not param:
            print(f"Current model: {client.model}")
        else:
            client.set_model(param)
            print(f"Model set to: {param}")

    elif command == "prompt":
        if not param:
            print(client.system_prompt or "(no system prompt set)")
        else:
            client.set_system_prompt(param)
            print("System prompt updated.")

    elif command == "loadp":
        name = param or input("Prompt filename: ")
        client.set_system_prompt(storage.load_prompt(name))
        print(f"Loaded system prompt from {name}")

    elif command == "savep":
        name = param or input("Prompt filename: ")
        storage.save_prompt(name, client.system_prompt)
        print(f"Saved system prompt to {name}")

    elif command == "param":
        try:
            key, value = param.split(" ", 1)
        except ValueError:
            print("Usage: /param <key> <value>")
        else:
            client.set_param(key, _coerce(value))
            print(f"{key} = {client.params[key]}")

    elif command == "params":
        for key, value in client.get_params().items():
            print(f"  {key} = {value}")

    elif command == "save":
        name = param or input("Context filename: ")
        storage.save_context(name, client.messages, client.system_prompt, client.model, client.get_params())
        print(f"Saved context to {name}")

    elif command == "load":
        name = param or input("Context filename: ")
        data = storage.load_context(name)
        client.messages = data["messages"]
        client.system_prompt = data["system_prompt"]
        if data["model"]:
            client.model = data["model"]
        if data["params"]:
            client.params.update(data["params"])
        print(f"Loaded context from {name}")

    elif command == "contexts":
        for name in storage.list_contexts():
            print(f"  {name}")

    elif command == "prompts":
        for name in storage.list_prompts():
            print(f"  {name}")

    elif command == "slice":
        try:
            client.slice_context(int(param))
        except ValueError:
            print("Usage: /slice <n>")

    elif command == "undo":
        client.undo_last()
        print("Removed last message.")

    elif command == "print":
        print(client.get_context_as_string())

    else:
        print(COMMANDS)

    return True


if __name__ == "__main__":
    main()
