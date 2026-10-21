# CLINK-LLM_CMD

A small Clink plugin and helper for AI-style inline prompts in `cmd.exe`.

The shell-side hook intercepts lines beginning with a configurable prefix (default: `>`), gathers a bit of contextual data, and prevents `cmd.exe` from executing the raw line. The helper builds a richer prompt (cwd + recent command history + any `!file.txt!` references + the textual request), then calls an OpenAI-compatible endpoint such as LM Studio.

Files in this repo:

- `clink_ai.lua` — Clink Lua plugin
- `ai_bridge.py` — helper that calls the LLM API and can also be invoked directly from other shells
- `clink_start.cmd` — example startup script

## Quick usage

1. Put `clink_ai.lua` in a Clink scripts directory
2. Put `ai_bridge.py` somewhere convenient
3. Set the environment variables for your backend
4. Start `cmd.exe` with Clink enabled
5. Type commands like:

```cmd
> summarize the current folder
> explain build errors
> what did I run last?
> summarize !README.md!
```

## Configuration

The default prefix is `>`.

You can override it before Clink loads scripts:

```cmd
set CLINK_AI_PREFIX=>
set CLINK_AI_BRIDGE=C:\path\to\ai_bridge.py
```

The bridge uses these env vars:

- `CLINK_AI_URL` — OpenAI-compatible chat completions URL
- `CLINK_AI_MODEL` — model name
- `CLINK_AI_API_KEY` — optional API key
- `CLINK_AI_TIMEOUT` — seconds (default 60)
- `CLINK_AI_PREFIX` — trigger prefix
- `CLINK_AI_BRIDGE` — helper script path

Example:

```cmd
set CLINK_AI_URL=http://localhost:1234/v1/chat/completions
set CLINK_AI_MODEL=local-model
set CLINK_AI_API_KEY=lm-studio
```

## Features

This example includes the first practical next-step features:

- `!file.txt!` references are detected and included in the request context
- recent command history is included when available from Clink's history file
- prompt construction is more structured and reusable
- the backend is directly callable from scripts, PowerShell, or bash wrappers

The idea is to keep the shell hook thin and the model logic reusable.

## Minimal example: local LM Studio

```cmd
set CLINK_AI_URL=http://localhost:1234/v1/chat/completions
set CLINK_AI_MODEL=local-model
set CLINK_AI_API_KEY=lm-studio
```

Then type:

```cmd
> explain the current directory and summarize !README.md!
```

## Backend reuse across shells

The backend is intentionally separate from the Clink hook. The same helper can be used from other wrappers.

Examples:

```cmd
python ai_bridge.py --prompt "summarize this folder" --cwd "%CD%" --files "README.md" --history "dir" 
```

```bash
python ai_bridge.py --prompt "summarize this folder" --cwd "$PWD" --files README.md --history "pwd\nls"
```

A PowerShell wrapper would call the same script with similar arguments. The shell-specific piece is just the front-end trigger; the actual model call stays in one reusable place.

## Why this is useful

This is intentionally thin: the shell plugin is only responsible for interception and routing. The AI logic lives in a helper script so it is easy to replace or extend with:

- local models
- remote LLM endpoints
- file-aware context fetchers
- command-history summarizers
- future PowerShell or Bash front-ends

## License

MIT
