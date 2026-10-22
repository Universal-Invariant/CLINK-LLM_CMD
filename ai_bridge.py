# ai_bridge.py
# Reusable shell-agnostic helper for calling an LLM from Clink, PowerShell, bash, etc.

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from urllib import error, request

DEFAULT_TIMEOUT = int(os.getenv("CLINK_AI_TIMEOUT", "60"))
MAX_SESSION_PAIRS = int(os.getenv("CLINK_AI_MAX_HISTORY", "8"))
MAX_MACRO_OUTPUT = int(os.getenv("CLINK_AI_MAX_MACRO_OUTPUT", "12000"))
MAX_HISTORY_LINES = int(os.getenv("CLINK_AI_MAX_HISTORY_LINES", "20"))
MAX_TERMINAL_CHARS = int(os.getenv("CLINK_AI_MAX_TERMINAL_CHARS", "20000"))

INJECTOR_REGISTRY = {}
RECURSION_MARKERS = [
    "$terminal$",
    "$history$",
    "$dir$",
    "$git$",
    "$cwd$",
    "$pwd$",
    "$last$",
    "$(",
    "@(",
]


def register_injector(name, func):
    if not callable(func):
        return
    key = (name or "").strip().lower().replace("-", "_")
    if key:
        INJECTOR_REGISTRY[key] = func


def normalize_injector_name(name):
    return (name or "").strip().lower().replace("-", "_")


def should_record_prompt_text(text):
    if text is None:
        return False
    value = str(text).strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith(">"):
        return False
    if any(
        marker in lowered
        for marker in [
            "$terminal$",
            "$history$",
            "$dir$",
            "$git$",
            "$cwd$",
            "$pwd$",
            "$(",
            "@(",
        ]
    ):
        return False
    return True


def register_builtin_injectors():
    def dir_injector(args_text="", **kwargs):
        cwd = kwargs.get("cwd") or os.getcwd()
        return run_shell_command("dir", cwd=cwd)

    def history_injector(args_text="", **kwargs):
        return (
            kwargs.get("history_text") or ""
        ).strip() or "No command history is available."

    def terminal_injector(args_text="", **kwargs):
        return read_terminal_log() or "No terminal output captured yet."

    def git_injector(args_text="", **kwargs):
        cwd = kwargs.get("cwd") or os.getcwd()
        return run_shell_command("git status --short --branch", cwd=cwd)

    def pwd_injector(args_text="", **kwargs):
        return kwargs.get("cwd") or os.getcwd()

    def last_injector(args_text="", **kwargs):
        value = os.getenv("LAST_COMMAND") or os.getenv("CLINK_LAST_COMMAND") or ""
        return value.strip() or "No recent command was captured."

    register_injector("dir", dir_injector)
    register_injector("history", history_injector)
    register_injector("terminal", terminal_injector)
    register_injector("git", git_injector)
    register_injector("git_status", git_injector)
    register_injector("cwd", pwd_injector)
    register_injector("pwd", pwd_injector)
    register_injector("last", last_injector)
    register_injector("last_command", last_injector)


register_builtin_injectors()


def load_injector_modules():
    raw_paths = (
        os.getenv("CLINK_AI_INJECTOR_PATHS")
        or os.getenv("CLINK_AI_CUSTOM_INJECTORS")
        or ""
    )
    paths = [
        p.strip()
        for p in raw_paths.replace(";", os.pathsep).split(os.pathsep)
        if p.strip()
    ]
    for path in paths:
        try:
            module_name = os.path.splitext(os.path.basename(path))[0]
            spec = importlib.util.spec_from_file_location(module_name, path)
            if not spec or not spec.loader:
                continue
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            registry = getattr(module, "INJECTORS", None) or getattr(
                module, "injectors", None
            )
            if isinstance(registry, dict):
                for name, func in registry.items():
                    register_injector(name, func)
        except Exception:
            pass


load_injector_modules()


def clean_url(base):
    if not base:
        return ""
    base = base.strip()
    if not base:
        return ""
    while base.endswith("/") and len(base) > 1:
        base = base[:-1]
    return base


def join_url(base, path):
    base = clean_url(base)
    path = str(path or "").strip().strip("/")
    if not path:
        return base
    if not base:
        return path
    return base + "/" + path


def is_full_endpoint(value):
    if not value:
        return False
    value = clean_url(value)
    return (
        bool(re.search(r"/(?:v1|api)/", value))
        or value.endswith("/chat/completions")
        or value.endswith("/api/chat")
    )


def resolve_api_url(explicit_url=None):
    if explicit_url:
        explicit = clean_url(explicit_url)
        if explicit:
            return explicit

    ordered = [
        ("CLINK_AI_URL", os.getenv("CLINK_AI_URL")),
        ("CLINK_AI_BASE_URL", os.getenv("CLINK_AI_BASE_URL")),
        ("LMSTUDIO_API_BASE", os.getenv("LMSTUDIO_API_BASE")),
        ("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL")),
        ("OLLAMA_HOST", os.getenv("OLLAMA_HOST")),
    ]

    for source_name, candidate in ordered:
        if candidate is None or not str(candidate).strip():
            continue

        value = clean_url(str(candidate).strip())
        if is_full_endpoint(value):
            return value

        if source_name == "OLLAMA_HOST":
            return join_url(value, "api/chat")

        if value.lower().endswith("/v1"):
            return join_url(value, "chat/completions")
        if value.lower().endswith("/api"):
            return join_url(value, "chat")

        if "ollama" in value.lower():
            return join_url(value, "api/chat")
        if (
            "lmstudio" in value.lower()
            or "localhost:1234" in value.lower()
            or "localhost:12349" in value.lower()
        ):
            return join_url(value, "v1/chat/completions")
        return join_url(value, "v1/chat/completions")

    return "http://localhost:12349/v1/chat/completions"


def resolve_model(explicit_model=None):
    if explicit_model:
        return explicit_model.strip()

    for name in ["CLINK_AI_MODEL", "OPENAI_MODEL", "LLM_MODEL"]:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return "local-model"


def resolve_api_key(explicit_key=None):
    if explicit_key:
        return explicit_key.strip()

    for name in ["CLINK_AI_API_KEY", "OPENAI_API_KEY"]:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return "lm-studio"


def terminal_log_path():
    env_candidates = [
        os.getenv("CLINK_AI_TERMINAL_LOG"),
        os.getenv("CLINK_AI_TERMINAL_LOG_PATH"),
    ]
    for candidate in env_candidates:
        if candidate and str(candidate).strip():
            return str(candidate).strip()

    base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
    return os.path.join(base, "clink-llm", "terminal_log.txt")


def read_terminal_log(max_chars=MAX_TERMINAL_CHARS):
    path = terminal_log_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(max_chars)
            return data.strip()
    except Exception:
        pass
    return ""


def append_terminal_log_entry(entry, path=None):
    if entry is None:
        return
    text = str(entry).strip()
    if not text:
        return
    if not should_record_prompt_text(text):
        return

    log_path = path or terminal_log_path()
    try:
        folder = os.path.dirname(log_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text)
            f.write("\n")
    except Exception:
        pass


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text_file(path, max_chars=20000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_chars)
    except Exception:
        return ""


def split_files(raw):
    if raw is None:
        return []
    items = []
    for part in raw.split(","):
        p = part.strip()
        if p:
            items.append(p)
    return items


def default_session_path():
    base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
    return os.path.join(base, "clink-llm", "chat_session.json")


def load_session_state(path=None):
    session_path = path or default_session_path()
    try:
        if os.path.exists(session_path):
            with open(session_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data.get("messages", [])
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def save_session_state(messages, path=None):
    session_path = path or default_session_path()
    try:
        folder = os.path.dirname(session_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        with open(session_path, "w", encoding="utf-8") as f:
            json.dump({"messages": messages}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def dedupe_recent_messages(messages):
    if not isinstance(messages, list):
        return []
    filtered = []
    last_user_text = None
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role == "user" and isinstance(content, str):
            candidate = content.strip()
            if candidate == last_user_text:
                continue
            last_user_text = candidate
        filtered.append(item)
    return filtered[-(MAX_SESSION_PAIRS * 2) :]


def trim_session_messages(messages):
    if not isinstance(messages, list):
        return []
    trimmed = []
    for item in messages:
        if isinstance(item, dict) and "role" in item and "content" in item:
            content = str(item["content"])[:8000]
            if item["role"] == "user" and not should_record_prompt_text(content):
                continue
            trimmed.append({"role": item["role"], "content": content})
    if len(trimmed) > MAX_SESSION_PAIRS * 2:
        trimmed = trimmed[-(MAX_SESSION_PAIRS * 2) :]
    return dedupe_recent_messages(trimmed)


def run_shell_command(command, cwd=None):
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = proc.stdout or ""
        if proc.stderr:
            output = output + ("\n" if output else "") + proc.stderr
        output = output.strip()
        if not output:
            return "[command produced no output]"
        return output[:MAX_MACRO_OUTPUT]
    except Exception as exc:
        return f"[command failed: {exc}]"


def resolve_builtin_value(name, cwd=None, history_text=""):
    token = (name or "").strip().lower()
    if not token:
        return ""

    if token in {"dir", "ls", "list", "folder", "cwdlist"}:
        return run_shell_command("dir", cwd)
    if token in {"history", "cmdhistory", "commandhistory"}:
        return history_text.strip() or "No command history is available."
    if token in {"terminal", "output", "console", "screen"}:
        return read_terminal_log() or "No terminal output captured yet."
    if token in {"git", "gitstatus", "status"}:
        return run_shell_command("git status --short --branch", cwd)
    if token in {"pwd", "cwd", "path"}:
        return cwd or os.getcwd()
    if token in {"last", "lastcommand", "lastcmd"}:
        value = os.getenv("LAST_COMMAND") or os.getenv("CLINK_LAST_COMMAND") or ""
        return value.strip() or "No recent command was captured."
    return ""


def call_registered_injector(name, args_text="", cwd=None, history_text=""):
    normalized = normalize_injector_name(name)
    func = INJECTOR_REGISTRY.get(normalized)
    if not callable(func):
        return f"[unknown injector: {name}]"
    try:
        try:
            return str(func(args_text, cwd=cwd, history_text=history_text))
        except TypeError:
            return str(func(args_text))
    except Exception as exc:
        return f"[injector failed: {name}: {exc}]"


def append_auto_context(prompt, cwd=None, history_text=""):
    if not prompt:
        return prompt

    p = prompt.strip()
    lower = p.lower()
    additions = []

    if (
        any(
            item in lower
            for item in [
                "current folder",
                "this folder",
                "current directory",
                "directory contents",
                "folder contents",
            ]
        )
        and "$dir$" not in p
        and "$(dir" not in p
        and "$(ls" not in p
    ):
        additions.append("\nCurrent folder contents:\n$dir$\n")
    if (
        any(
            item in lower
            for item in [
                "what did i run last",
                "history",
                "recent commands",
                "command history",
            ]
        )
        and "$history$" not in p
        and "$(git" not in p
    ):
        additions.append("\nRecent command history:\n$history$\n")
    if any(
        item in lower
        for item in [
            "build errors",
            "terminal output",
            "errors",
            "last output",
            "console",
        ]
    ):
        additions.append("\nRecent terminal context:\n$terminal$\n")

    if additions:
        return p + "\n" + "\n".join(additions)
    return p


def expand_prompt_macros(text, cwd=None, history_text="", limit=MAX_MACRO_OUTPUT):
    if not text:
        return text

    def replace_match(match):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        token = inner.strip()
        if not token:
            return ""

        if token.startswith("$") and token.endswith("$"):
            token = token[1:-1]

        builtin = resolve_builtin_value(token, cwd=cwd, history_text=history_text)
        if builtin:
            return builtin[:limit]

        return run_shell_command(token, cwd)[:limit]

    return re.sub(r"\$\((.*?)\)|\$([^$\n]+?)\$", replace_match, text)


def build_user_message(job):
    cwd = job.get("cwd", "") or os.getcwd()
    history = job.get("history", "")
    prompt = expand_prompt_macros(job.get("prompt", ""), cwd=cwd, history_text=history)
    files = job.get("files", [])

    file_snippets = []
    for file in files:
        text = read_text_file(file)
        if text:
            file_snippets.append(
                f"\n--- FILE: {file} ---\n{text[:20000]}\n--- END FILE ---\n"
            )

    file_section = "\n".join(file_snippets)
    history_section = f"\nRecent command history:\n{history}\n" if history else ""

    mode = (job.get("mode") or "chat").lower()
    if mode == "cmd":
        assistant_mode = "You are a shell command suggestion assistant. Return only a concise, valid command or a short explanation with the command first."
    else:
        assistant_mode = "You are a helpful terminal assistant. Keep replies brief, actionable, and shell-aware."

    return (
        f"{assistant_mode}\n"
        f"Current directory: {cwd}\n"
        f"{history_section}"
        f"{file_section}\n"
        f"User request: {prompt}\n"
    )


def build_prompt_from_args(args):
    files = []
    for item in args.files or []:
        files.extend(split_files(item))

    file_snippets = []
    for file in files:
        text = read_text_file(file)
        if text:
            file_snippets.append(
                f"\n--- FILE: {file} ---\n{text[:20000]}\n--- END FILE ---\n"
            )

    file_section = "\n".join(file_snippets)
    history_section = (
        f"\nRecent command history:\n{args.history}\n" if args.history else ""
    )
    cwd = args.cwd or os.getcwd()
    prompt = expand_prompt_macros(
        args.prompt or "", cwd=cwd, history_text=args.history or ""
    )
    mode = (args.mode or "chat").lower()

    if mode == "cmd":
        assistant_mode = "You are a shell command suggestion assistant. Return only a concise, valid command or a short explanation with the command first."
    else:
        assistant_mode = "You are a helpful terminal assistant. Keep replies brief, actionable, and shell-aware."

    return (
        f"{assistant_mode}\n"
        f"Current directory: {cwd}\n"
        f"{history_section}"
        f"{file_section}\n"
        f"User request: {prompt}\n"
    )


def call_provider(
    prompt, api_url=None, model=None, api_key=None, prior_messages=None, mode="chat"
):
    url = resolve_api_url(api_url)
    model_name = resolve_model(model)
    key_value = resolve_api_key(api_key)

    mode_name = (mode or "chat").lower()
    if mode_name == "cmd":
        system_text = "You are a shell command suggestion assistant for Windows cmd.exe. Prefer concise, valid commands and do not invent unsupported flags."
    else:
        system_text = "You are a helpful terminal assistant for the Windows command line. Use prior conversation context when present. Keep replies brief, actionable, shell-aware, and command-oriented."

    messages = [
        {
            "role": "system",
            "content": system_text,
        }
    ]

    if prior_messages:
        for item in prior_messages:
            if isinstance(item, dict) and "role" in item and "content" in item:
                messages.append({"role": item["role"], "content": item["content"]})

    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 512,
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {key_value}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "choices" in data and data["choices"]:
                content = data["choices"][0]["message"]["content"]
                return content, messages
            if "message" in data:
                content = data["message"].get("content", "")
                return content, messages
            return json.dumps(data, indent=2), messages
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"AI request failed (HTTP {e.code}): {body}", messages
    except Exception as e:
        return f"AI request failed: {e.__class__.__name__}: {e}", messages


def dump_debug_state(session_file=None, cwd=None):
    session_file = session_file or default_session_path()
    messages = load_session_state(session_file)
    lines = []
    lines.append("CLINK-LLM_CMD debug")
    lines.append(f"cwd: {cwd or os.getcwd()}")
    lines.append(f"session_file: {session_file}")
    lines.append(f"session_turns: {len(messages)}")
    lines.append(f"provider_url: {resolve_api_url()}")
    lines.append(f"model: {resolve_model()}")
    lines.append(f"api_key_present: {bool(resolve_api_key())}")
    lines.append(f"max_history_pairs: {MAX_SESSION_PAIRS}")
    lines.append(f"max_macro_output: {MAX_MACRO_OUTPUT}")
    lines.append(f"terminal_log_path: {terminal_log_path()}")
    lines.append(f"registered_injectors: {sorted(INJECTOR_REGISTRY.keys())}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", help="path to a JSON job file")
    parser.add_argument("--prompt", help="prompt text")
    parser.add_argument("--cwd", help="working directory")
    parser.add_argument("--history", help="recent command history")
    parser.add_argument("--files", nargs="*", help="file names or paths to include")
    parser.add_argument(
        "--api-url", help="override the provider base or full endpoint URL"
    )
    parser.add_argument("--model", help="override the model name")
    parser.add_argument("--api-key", help="override the API key")
    parser.add_argument(
        "--session-file", help="path to session file for conversation persistence"
    )
    parser.add_argument("--mode", default="chat", help="chat or cmd")
    parser.add_argument(
        "--reset-session", action="store_true", help="clear the current session file"
    )
    parser.add_argument("--debug", action="store_true", help="print debug information")
    parser.add_argument(
        "--log-entry", help="append a terminal entry to the transcript log"
    )
    args = parser.parse_args()

    if args.log_entry:
        append_terminal_log_entry(args.log_entry)
        return 0

    if args.job:
        try:
            job = load_json(args.job)
        except Exception as e:
            print(f"Failed to read job: {e}")
            return 1

        session_file = (
            job.get("session_file") or args.session_file or default_session_path()
        )
        prior_messages = trim_session_messages(load_session_state(session_file))
        mode = (job.get("mode") or args.mode or "chat").lower()

        if args.reset_session:
            save_session_state([], session_file)
            print("Session reset.")
            return 0

        if args.debug:
            print(
                dump_debug_state(
                    session_file, job.get("cwd") or args.cwd or os.getcwd()
                )
            )
            return 0

        prompt = build_user_message(job)
    else:
        session_file = args.session_file or default_session_path()
        prior_messages = trim_session_messages(load_session_state(session_file))
        mode = (args.mode or "chat").lower()

        if args.reset_session:
            save_session_state([], session_file)
            print("Session reset.")
            return 0

        if args.debug:
            print(dump_debug_state(session_file, args.cwd or os.getcwd()))
            return 0

        prompt = build_prompt_from_args(args)
    result, messages = call_provider(
        prompt,
        api_url=args.api_url,
        model=args.model,
        api_key=args.api_key,
        prior_messages=prior_messages,
        mode=mode,
    )

    if prior_messages:
        conversation = trim_session_messages(
            prior_messages
            + [
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": result},
            ]
        )
    else:
        conversation = [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": result},
        ]
    save_session_state(conversation, session_file)

    print("")
    print("AI response:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
