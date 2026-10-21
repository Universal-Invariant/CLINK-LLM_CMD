# CLINK-LLM_CMD

A lightweight Clink frontend for routing inline command prompts to an LLM backend.

The shell-side hook intercepts lines beginning with a configurable prefix (default: `>`), captures useful context (cwd, recent history, and `!file.txt!` references), and prevents the original raw line from being executed by `cmd.exe`. It then hands the job off to a Python helper that calls an OpenAI-compatible or provider-specific endpoint.

Files in this repo:

- `clink_ai.lua` — Clink Lua plugin
- `ai_bridge.py` — reusable helper that calls an LLM backend and can also be invoked directly from PowerShell, bash, or other scripts
- `clink_start.cmd` — minimal startup script

## Quick usage

1. Put `clink_ai.lua` in a Clink scripts directory.
2. Put `ai_bridge.py` somewhere convenient.
3. Set your environment variables.
4. Start `cmd.exe` with Clink enabled.
5. Type prompts such as:

```cmd
> summarize the current folder
> explain build errors
> what did I run last?
> summarize !README.md!
```

## Configuration

The default trigger prefix is `>`.

You can override it before Clink loads scripts:

```cmd
set CLINK_AI_PREFIX=>
set CLINK_AI_BRIDGE=C:\path\to\ai_bridge.py
```

The bridge resolves its backend configuration with a layered fallback strategy:

- `CLINK_AI_URL` (preferred)
- `CLINK_AI_BASE_URL`
- `LMSTUDIO_API_BASE`
- `OPENAI_BASE_URL`
- `OLLAMA_HOST`
- default: `http://localhost:12349` for local fallbacks

It also resolves model and key using similar fallbacks:

- `CLINK_AI_MODEL`
- `OPENAI_MODEL`
- `LLM_MODEL`
- default model: `local-model`

- `CLINK_AI_API_KEY`
- `OPENAI_API_KEY`
- default dummy key: `lm-studio`

Example:

```cmd
set CLINK_AI_URL=http://localhost:1234/v1/chat/completions
set CLINK_AI_MODEL=local-model
set CLINK_AI_API_KEY=lm-studio
```

Example using OpenAI-compatible local endpoints:

```cmd
set OPENAI_BASE_URL=http://localhost:12349
set OPENAI_MODEL=google/gemma-3-12b
set OPENAI_API_KEY=AnyKey
```

Example using Ollama:

```cmd
set OLLAMA_HOST=http://localhost:12349
set LLM_MODEL=llama3.2
```

## Why the bridge is Python

Clink itself must be Lua because it is a Lua-based extension host. The AI bridge does not need to be Lua, and in practice Python is a better fit for HTTP, JSON, file reading, and backend abstraction.

The pattern is deliberately split:

- `clink_ai.lua` handles shell interception and route selection.
- `ai_bridge.py` handles model calls, file context, and provider normalization.

This keeps the shell hook thin while making the model layer easier to reuse from PowerShell, bash, or other scripts.

## Provider URL normalization

The bridge does not force a single path for all providers. Different providers use different API shapes.

Examples:

- OpenAI-compatible local servers: `http://host:port/v1/chat/completions`
- Ollama: `http://host:port/api/chat`
- LM Studio: often `http://host:port/v1/chat/completions`

The resolver should normalize this automatically instead of requiring one hard-coded path. That makes the tool more robust across providers and avoids forcing the user to match one API layout.

## Features

This project currently includes:

- `!file.txt!` reference detection
- recent command history capture
- current working directory context
- provider-aware URL selection and fallback
- direct backend invocation from Python scripts and shell wrappers

## Backend reuse across shells

The backend is intentionally separate from the Clink hook. The same helper can be reused from other wrappers.

Examples:

```cmd
python ai_bridge.py --prompt "summarize this folder" --cwd "%CD%" --files README.md --history "dir"
```

```bash
python ai_bridge.py --prompt "summarize this folder" --cwd "$PWD" --files README.md --history "pwd\nls"
```

A PowerShell wrapper would call the same script with similar arguments. The shell-specific piece is just the front-end trigger; the actual model call stays in one reusable place.

## Future enhancements

Planned follow-up improvements for this project:

- Add true asynchronous job processing so the shell remains responsive while the model runs.
- Add a more structured parser for commands like `> summarize !README.md!` and `> explain build errors`.
- Include richer context such as current git status, recent directory listing, environment summary, and selected file metadata.
- Add a status indicator or prompt update so users can tell when a model request is queued, running, or complete.
- Add a PowerShell wrapper and bash/zsh wrapper that call the same backend contract as Clink.
- Add input validation and safer file-path handling for local file context injection.
- Add support for more provider-specific endpoints beyond OpenAI-compatible ones.
- Add result caching and a lightweight request log for repeat prompts.
- Add a non-blocking queue directory and worker model for cleaner asynchronous output.
- Add a simple plugin configuration file for default prefix, model, and backend settings.

## License

MIT
