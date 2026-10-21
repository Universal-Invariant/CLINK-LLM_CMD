# ai_bridge.py
# Reusable shell-agnostic helper for calling an LLM from Clink, PowerShell, bash, etc.

import argparse
import json
import os
import sys
from urllib import request, error

DEFAULT_TIMEOUT = int(os.getenv("CLINK_AI_TIMEOUT", "60"))


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


def call_openai_compatible(prompt):
    url = os.getenv("CLINK_AI_URL") or "http://localhost:1234/v1/chat/completions"
    model = os.getenv("CLINK_AI_MODEL") or "local-model"
    api_key = os.getenv("CLINK_AI_API_KEY") or "lm-studio"

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
            return data["choices"][0]["message"]["content"]
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

    result = call_openai_compatible(prompt)

    print("")
    print("AI response:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
