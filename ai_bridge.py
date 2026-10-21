# ai_bridge.py
# Helper used by Clink to send a prompt to an LLM endpoint.
# Works with LM Studio or any OpenAI-compatible API.

import argparse
import json
import os
import sys
from urllib import request, error


def load_job(job_path):
    with open(job_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(job):
    # Very lightweight structure; later expand with file refs and command history.
    text = job.get("prompt", "")
    cwd = job.get("cwd", "")
    return (
        "You are a helpful terminal assistant.\n"
        f"Current directory: {cwd}\n\n"
        f"User request: {text}\n"
    )


def call_openai_compatible(prompt):
    url = os.getenv("CLINK_AI_URL") or "http://localhost:1234/v1/chat/completions"
    model = os.getenv("CLINK_AI_MODEL") or "local-model"
    api_key = os.getenv("CLINK_AI_API_KEY") or "lm-studio"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a helpful terminal assistant for the Windows command line."},
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
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return f"AI request failed (HTTP {e.code}): {body}"
    except Exception as e:
        return f"AI request failed: {e.__class__.__name__}: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", help="path to the JSON job file")
    args = parser.parse_args()

    if not args.job:
        print("No job file provided.")
        return 1

    try:
        job = load_job(args.job)
    except Exception as e:
        print(f"Failed to read job: {e}")
        return 1

    prompt = build_prompt(job)
    result = call_openai_compatible(prompt)

    print("")
    print("AI response:")
    print("-" * 60)
    print(result)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
