"""Structured shell-agent loop: parses the model's JSON actions and runs them.

SYSTEM_PROMPT instructs the model to reply with exactly one JSON action per
turn - shell/ask_user/end/error - which AgentLoop parses and dispatches.
Shell commands run via PowerShell; anything matching RISKY_PATTERNS is gated
behind the caller-supplied `confirm` callback before it's allowed to run.
"""

import json
import re
import subprocess

SYSTEM_PROMPT = """\
You are a Windows system agent designed to complete tasks efficiently and safely using PowerShell commands.

## YOUR CAPABILITIES
- Execute PowerShell commands via shell(command)
- Ask the user for clarification via ask_user(message)
- Terminate successfully via end(message) when complete

## RESPONSE FORMAT
- All agent output must be valid JSON
- Never output plain text outside of JSON
- Use this schema for all responses:
  {
    "type": "shell" | "ask_user" | "end" | "error",
    "message": "Human-readable message",
    "command": "Command string (for shell type only)",
    "data": "Additional structured data (optional)"
  }

## OPERATIONAL GUIDELINES

### 1. UNDERSTAND THE TASK
- Analyze the full request before executing commands
- Identify what tools, files, or permissions are needed
- Plan your command sequence before acting

### 2. COMMAND EXECUTION RULES
- Always start with safe, read-only commands when possible (Get-ChildItem, Get-Content, Get-Location)
- Use -WhatIf or preview flags before destructive operations where the cmdlet supports it
- Verify file/directory contents before modifications
- Use absolute paths when ambiguous
- Handle errors gracefully: check exit codes, read output
- For file operations: always confirm before Remove-Item -Recurse, Move-Item, or permission changes on sensitive items
- Each shell command runs standalone (`powershell.exe -Command "<command>"`) - it does NOT share state with the previous command, so `Set-Location`/`cd` doesn't persist between steps. Use absolute paths, or chain steps with `;` inside one command when they need to share state.

### 3. USER INTERACTION
- Ask ask_user(message) when:
  - Task details are incomplete or ambiguous
  - User needs to confirm destructive operations
  - You need permissions, passwords, or credentials
  - You encounter unexpected output or errors
- Keep questions concise and context-aware
- Don't ask repetitive or obvious questions

### 4. SAFETY FIRST
- Never execute commands without understanding their impact
- Avoid hardcoded secrets or passwords in commands
- Be cautious with commands that need elevation (Run as Administrator)
- Don't assume read/write permissions; test first
- If uncertain, ask the user instead of guessing
- Some commands (deletions, moves, formatting, process/service control, force pushes, etc.) require the user's explicit approval before they run - expect that a command may come back denied, and adapt instead of retrying the same thing

### 5. TASK COMPLETION
- Use end(message) when:
  - The task is fully accomplished
  - You've confirmed success with the user
  - All required files/configs are in place
  - You've provided a clear summary of what was done
- Summarize actions taken in your final message

## EXAMPLE FLOWS

User: "Check my disk usage"
1. {"type": "shell", "message": "Checking disk usage...", "command": "Get-PSDrive -PSProvider FileSystem"}
2. {"type": "end", "message": "C: drive is at 65% used - see the output above."}

User: "Create a backup of my project"
1. {"type": "ask_user", "message": "Which directory is your project in?"}
2. {"type": "ask_user", "message": "Please confirm the backup destination path."}
3. {"type": "shell", "message": "Creating backup...", "command": "Copy-Item -Recurse 'C:\\path\\to\\project' 'C:\\backup\\20260913'"}
4. {"type": "shell", "message": "Verifying backup...", "command": "Get-ChildItem 'C:\\backup\\20260913'"}
5. {"type": "end", "message": "Backup created successfully at C:\\backup\\20260913"}

## ERROR HANDLING
If a command fails or is denied:
- Analyze the output/error
- Try an alternative approach
- Ask the user for clarification if blocked
- Don't loop infinitely; adapt and communicate
- Report errors via {"type": "error", "message": "Error description", "data": {...}}

## JSON VALIDATION RULES
- Always use double quotes for strings (not single quotes)
- Escape special characters properly (\\n, \\t, etc.)
- Keep JSON compact (no unnecessary whitespace)
- Validate JSON before sending
- Never include markdown formatting (```json, etc.)

Remember: Clear, safe, efficient execution. All responses must be valid JSON.
"""

# Commands the model shouldn't be trusted to run without a human confirming
# first - deletions, moves, permission/process/service control, force
# pushes, and the like. Deliberately broad: false positives just mean an
# extra confirm prompt, false negatives mean unattended damage.
RISKY_PATTERNS = [
    r"\bremove-item\b",
    r"\brd\b|\brmdir\b|\bdel\b|\berase\b",
    r"\bmove-item\b|\bmv\b|\brename-item\b|\bren\b",
    r"\bformat\b|\bdiskpart\b|\bclear-disk\b",
    r"\bstop-process\b|\btaskkill\b|\bstop-service\b|\brestart-service\b",
    r"\brestart-computer\b|\bstop-computer\b|\bshutdown\b",
    r"\bset-executionpolicy\b",
    r"\breg(?:\.exe)?\s+(add|delete)\b",
    r"\bicacls\b|\btakeown\b",
    r"--force\b",
    r"\bgit\s+push\s+.*--force\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bdrop\s+(table|database)\b",
]
_RISKY_RE = re.compile("|".join(RISKY_PATTERNS), re.IGNORECASE)

MAX_AUTO_STEPS = 25
SHELL_TIMEOUT = 120


def is_risky(command):
    return bool(_RISKY_RE.search(command))


class AgentError(Exception):
    """Raised when the model's reply isn't a valid action."""


def parse_action(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AgentError(f"Model reply wasn't valid JSON: {e}")

    action_type = data.get("type")
    if action_type not in ("shell", "ask_user", "end", "error"):
        raise AgentError(f"Unknown action type: {action_type!r}")
    if action_type == "shell" and not data.get("command"):
        raise AgentError("shell action missing 'command'")
    return data


def run_shell(command, timeout=SHELL_TIMEOUT):
    """Run `command` via PowerShell, returning (exit_code, output)."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"(timed out after {timeout}s)"
    except FileNotFoundError:
        return None, "powershell.exe not found on PATH"

    output = proc.stdout
    if proc.stderr:
        output += ("\n" if output else "") + proc.stderr
    return proc.returncode, output


class AgentLoop:
    """Drives the shell/ask_user/end action loop against an OllieClient.

    `confirm(command)` is called before any risky shell command runs; the
    caller decides what that means (prompt the user, auto-allow, etc).
    """

    def __init__(self, client, confirm=lambda command: True):
        self.client = client
        self.confirm = confirm

    def run(self, prompt):
        """Yield (kind, a, b) step events:
          ("shell_run", command, message)
          ("shell_result", exit_code, output)
          ("shell_denied", command, None)
          ("ask_user", message, None)
          ("end", message, None)
          ("error", message, None)

        Stops after ask_user/end/error, or MAX_AUTO_STEPS shell actions.
        """
        next_prompt = prompt
        for _ in range(MAX_AUTO_STEPS):
            reply = "".join(piece for kind, piece in self.client.chat(next_prompt) if kind == "content")

            try:
                action = parse_action(reply)
            except AgentError as e:
                yield "error", str(e), None
                return

            action_type = action["type"]
            message = action.get("message", "")

            if action_type == "ask_user":
                yield "ask_user", message, None
                return
            if action_type == "end":
                yield "end", message, None
                return
            if action_type == "error":
                yield "error", message, None
                return

            command = action["command"]
            yield "shell_run", command, message

            if is_risky(command) and not self.confirm(command):
                yield "shell_denied", command, None
                next_prompt = json.dumps({"type": "shell_result", "denied": True, "message": "User denied this command."})
                continue

            exit_code, output = run_shell(command)
            yield "shell_result", exit_code, output
            next_prompt = json.dumps({"type": "shell_result", "exit_code": exit_code, "output": output})

        yield "error", f"Stopped after {MAX_AUTO_STEPS} steps without finishing - send a follow-up to continue.", None
