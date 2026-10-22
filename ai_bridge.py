# ai_bridge.py
# Reusable shell-agnostic helper for calling an LLM from Clink, PowerShell, bash, etc.

import argparse
import json
import os
import re
import subprocess
import sys
from urllib import error, request

DEFAULT_TIMEOUT = int(os.getenv("CLINK_AI_TIMEOUT", "60"))
MAX_SESSION_PAIRS = int(os.getenv("CLINK_AI_MAX_HISTORY", "8"))


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
    return bool(re.search(r"/(?:v1|api)/", value)) or value.endswith("/chat/completions") or value.endswith("/api/chat")


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
        if "lmstudio" in value.lower() or "localhost:1234" in value.lower() or "localhost:12349" in value.lower():
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


def trim_session_messages(messages):
    if not isinstance(messages, list):
        return []
    trimmed = []
    for item in messages:
        if isinstance(item, dict) and "role" in item and "content" in item:
            trimmed.append({"role": item["role"], "content": str(item["content"])[:8000]})
    if len(trimmed) > MAX_SESSION_PAIRS * 2:
        trimmed = trimmed[-(MAX_SESSION_PAIRS * 2):]
    return trimmed


def expand_prompt_macros(text, cwd=None, limit=20000):
    if not text:
        return text

    cwd = cwd or os.getcwd()
    alias_map = {
        "dir": "dir",
        "cwd": "cd",
        "pwd": "cd",
        "path": "cd",
    }

    def replace_match(match):
        inner = match.group(1) if match.group(1) is not None else match.group(2)
        command = inner.strip()
        if not command:
            return ""

        command = command.replace("|>", "|")
        lowered = command.strip().lower()
        if lowered in alias_map:
            command = alias_map[lowered]

        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = (proc.stdout or "") + ("\n" + (proc.stderr or "") if proc.stderr else "")
            output = output.strip()
            if not output:
                return "[command produced no output]"
            return output[:limit]
        except Exception as exc:
            return f"[command failed: {exc}]"

    expanded = re.sub(r"\$\((.*?)\)|\$([^$\n]+?)\$", replace_match, text)
    return expanded


def build_user_message(job):
    prompt = expand_prompt_macros(job.get("prompt", ""), cwd=job.get("cwd", "") or os.getcwd())
    cwd = job.get("cwd", "")
    history = job.get("history", "")
    files = job.get("files", [])

    file_snippets = []
    for file in files:
        text = read_text_file(file)
        if text:
            file_snippets.append(f"\n--- FILE: {file} ---\n{text[:20000]}\n--- END FILE ---\n")

    file_section = "\n".join(file_snippets)
    history_section = f"\nRecent command history:\n{history}\n" if history else ""

    return (
        "You are a helpful terminal assistant.\n"
        f"Current directory: {cwd}\n"
        f"{history_section}"
        f"{file_section}\n"
        f"User request: {prompt}\n"
    )


def build_prompt_from_args(args):
    files = []
    for item in (args.files or []):
        files.extend(split_files(item))

    file_snippets = []
    for file in files:
        text = read_text_file(file)
        if text:
            file_snippets.append(f"\n--- FILE: {file} ---\n{text[:20000]}\n--- END FILE ---\n")

    file_section = "\n".join(file_snippets)
    history_section = f"\nRecent command history:\n{args.history}\n" if args.history else ""
    prompt = expand_prompt_macros(args.prompt or "", cwd=args.cwd or os.getcwd())

    return (
        "You are a helpful terminal assistant.\n"
        f"Current directory: {args.cwd or os.getcwd()}\n"
        f"{history_section}"
        f"{file_section}\n"
        f"User request: {prompt}\n"
    )


def call_provider(prompt, api_url=None, model=None, api_key=None, prior_messages=None):
    url = resolve_api_url(api_url)
    model_name = resolve_model(model)
    key_value = resolve_api_key(api_key)

    messages = [{
        "role": "system",
        "content": "You are a helpful terminal assistant for the Windows command line. Use prior conversation context when present. Keep replies brief, actionable, shell-aware, and command-oriented."
    }]

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", help="path to a JSON job file")
    parser.add_argument("--prompt", help="prompt text")
    parser.add_argument("--cwd", help="working directory")
    parser.add_argument("--history", help="recent command history")
    parser.add_argument("--files", nargs="*", help="file names or paths to include")
    parser.add_argument("--api-url", help="override the provider base or full endpoint URL")
    parser.add_argument("--model", help="override the model name")
    parser.add_argument("--api-key", help="override the API key")
    parser.add_argument("--session-file", help="path to session file for conversation persistence")
    args = parser.parse_args()

    if args.job:
        try:
            job = load_json(args.job)
        except Exception as e:
            print(f"Failed to read job: {e}")
            return 1
        session_file = job.get("session_file") or args.session_file or default_session_path()
        prior_messages = trim_session_messages(load_session_state(session_file))
        prompt = build_user_message(job)
    else:
        session_file = args.session_file or default_session_path()
        prior_messages = trim_session_messages(load_session_state(session_file))
        prompt = build_prompt_from_args(args)

    result, messages = call_provider(
        prompt,
        api_url=args.api_url,
        model=args.model,
        api_key=args.api_key,
        prior_messages=prior_messages,
    )

    if prior_messages:
        conversation = trim_session_messages(prior_messages + [{"role": "user", "content": prompt}, {"role": "assistant", "content": result}])
    else:
        conversation = [{"role": "user", "content": prompt}, {"role": "assistant", "content": result}]
    save_session_state(conversation, session_file)

    print("")
    print("AI response:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
