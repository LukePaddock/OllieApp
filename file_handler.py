"""Read-only browser for pulling arbitrary filesystem files into the chat context.

Unlike storage_handler.py (which manages ollie's own prompts/ and context/
directories), this walks wherever you point it - the pwd, an absolute path,
a subdirectory - so /file can add any file's contents to the conversation.
"""

import os

MAX_FILE_BYTES = 256 * 1024


class FileHandler:
    def __init__(self, base_dir="."):
        self.base_dir = os.path.abspath(base_dir)

    def resolve(self, path):
        expanded = os.path.expanduser(path) if path else self.base_dir
        if not os.path.isabs(expanded):
            expanded = os.path.join(self.base_dir, expanded)
        return os.path.normpath(expanded)

    def list_dir(self, path=""):
        full = self.resolve(path)
        if not os.path.isdir(full):
            raise NotADirectoryError(f"Not a directory: {full}")
        entries = sorted(os.listdir(full))
        return [e + "/" if os.path.isdir(os.path.join(full, e)) else e for e in entries]

    def read_file(self, path):
        full = self.resolve(path)
        if os.path.isdir(full):
            raise IsADirectoryError(f"Is a directory: {full}")
        if not os.path.isfile(full):
            raise FileNotFoundError(f"File not found: {full}")

        size = os.path.getsize(full)
        if size > MAX_FILE_BYTES:
            raise ValueError(f"File too large ({size:,} bytes, limit is {MAX_FILE_BYTES:,}): {full}")

        try:
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            raise ValueError(f"Not a text file (couldn't decode as UTF-8): {full}")

        return full, content
