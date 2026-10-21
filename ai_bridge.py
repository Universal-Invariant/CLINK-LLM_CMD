# ai_bridge.py
# Reusable shell-agnostic helper for calling an LLM from Clink, PowerShell, bash, etc.

import argparse
import json
import os
import re
import sys
from urllib import error, request

DEFAULT_TIMEOUT = int(os.getenv("CLINK_AI_TIMEOUT", "60"))


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

    candidate_sources = [
        ("CLINK_AI_URL", os.getenv("CLINK_AI_URL")),
        ("CLINK_AI_BASE_URL", os.getenv("CLINK_AI_BASE_URL")),
        ("LMSTUDIO_API_BASE", os.getenv("LMSTUDIO_API_BASE")),
        ("OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL")),
        ("OLLAMA_HOST", os.getenv("OLLAMA_HOST")),
    ]

    for source_name, value in candidate_sources:
        if not value or not str(value).strip():
            continue

        v = clean_url(str(value).strip())

        if source_name == "OLLAMA_HOST":
            if is_full_endpoint(v):
                return v
            return join_url(v, "api/chat")

        if source_name in ("CLINK_AI_URL", "LMSTUDIO_API_BASE", "OPENAI_BASE_URL", "CLINK_AI_BASE_URL"):
            if is_full_endpoint(v):
                return v
            return join_url(v, "v1/chat/completions")

    return "http://localhost:12349/v1/chat/completions"

def resolve_model(explicit_model=None):
    if explicit_model:
        return explicit_model.strip()

    for name in [
        "CLINK_AI_MODEL",
        "OPENAI_MODEL",
        "LLM_MODEL",
    ]:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()

    return "local-model"


def resolve_api_key(explicit_key=None):
    if explicit_key:
        return explicit_key.strip()

    for name in [
        "CLINK_AI_API_KEY",
        "OPENAI_API_KEY",
    ]:
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
            data = f.read(max_chars)
        return data
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


def build_prompt_from_job(job):
    prompt = job.get("prompt", "")
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

    return (
        "You are a helpful terminal assistant.\n"
        f"Current directory: {args.cwd or os.getcwd()}\n"
        f"{history_section}"
        f"{file_section}\n"
        f"User request: {args.prompt or ''}\n"
    )


def call_provider_chat(prompt, api_url=None, model=None, api_key=None):
    url = resolve_api_url(api_url)
    model = resolve_model(model)
    api_key = resolve_api_key(api_key)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful terminal assistant for the Windows command line."
            },
            {"role": "user", "content": prompt},
        ],
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
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"]
            if "message" in data:
                return data["message"].get("content", "")
            return json.dumps(data, indent=2)
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"AI request failed (HTTP {e.code}): {body}"
    except Exception as e:
        return f"AI request failed: {e.__class__.__name__}: {e}"


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
    args = parser.parse_args()

    if args.job:
        try:
            job = load_json(args.job)
        except Exception as e:
            print(f"Failed to read job: {e}")
            return 1
        prompt = build_prompt_from_job(job)
    else:
        prompt = build_prompt_from_args(args)

    result = call_provider_chat(
        prompt,
        api_url=args.api_url,
        model=args.model,
        api_key=args.api_key,
    )

    print("")
    print("AI response:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
