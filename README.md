# CLINK-LLM_CMD

A tiny Clink plugin and bridge for AI-style inline prompts in `cmd.exe`.

The shell-side hook intercepts lines beginning with a configurable prefix (default: `>`), calls a helper process, and prevents cmd.exe from executing the raw line. The helper builds context (cwd, recent history, maybe file refs), calls an OpenAI-compatible API (such as LM Studio), and prints the result.

Files in this repo:

- `clink_ai.lua` — Clink Lua plugin
- `ai_bridge.py` — helper that calls the LLM API
- `clink_start.cmd` — example startup script for suppressing the default CMD banner and optionally running a custom prompt

## Quick usage

1. Put `clink_ai.lua` in a Clink scripts directory
2. Put `ai_bridge.py` somewhere convenient
3. Edit environment variables or defaults in the scripts
4. Start `cmd.exe` with Clink enabled
5. Type commands like:

```cmd
> summarize the current folder
> explain build errors
> what did I run last?
```

## Configuration

The default prefix is `>`.

You can override it before Clink loads scripts:

```cmd
set CLINK_AI_PREFIX=>
set CLINK_AI_BRIDGE=C:\path\to\ai_bridge.py
```

The bridge uses env vars:

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

## Notes about the CMD banner / copyright message

The default Microsoft `cmd.exe` banner is a Clink setting, not a Windows requirement. Best practice is to hide it via Clink itself:

```cmd
clink set clink.logo none
```

or:

```cmd
clink set clink.logo short
```

Do not rely on `cls` in autorun if you also use a custom prompt such as Oh My Posh. `cls` clears the screen and can interfere with prompt setup/rendering. In other words, `cls` is a blunt tool; it often runs too early and destroys the formatting state that the prompt expects.

If you want to clear the screen, do it after the prompt is initialized, typically as the last line in a `clink_start.cmd` script or after `oh-my-posh` initialization. If you want the cleanest setup, prefer `clink set clink.logo none` and leave the prompt to render normally.

## Minimal example: local LM Studio

```cmd
set CLINK_AI_URL=http://localhost:1234/v1/chat/completions
set CLINK_AI_MODEL=local-model
set CLINK_AI_API_KEY=lm-studio
```

Then type:

```cmd
> explain the current directory and give me a quick summary
```

## Why this is useful

This is intentionally thin: the shell plugin is only responsible for interception and routing. The AI logic lives in a helper script so it is easy to replace or extend with:

- local models
- remote LLM endpoints
- file-aware context fetchers
- command-history summarizers
- future PowerShell or Bash front-ends

## License

MIT
