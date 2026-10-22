# CLINK-LLM_CMD

A lightweight Clink frontend for routing inline command prompts to an LLM backend.

The shell-side hook intercepts lines beginning with a configurable prefix (default: `>`), captures useful context (cwd, recent history, and `!file.txt!` references), and prevents the original raw line from being executed by `cmd.exe`. It then hands the job off to a Python helper that calls an OpenAI-compatible or provider-specific endpoint.

Files in this repo:

- `clink_ai.lua` — Clink Lua plugin
- `ai_bridge.py` — reusable Python backend that calls an LLM API and can also be invoked directly from PowerShell, bash, or other scripts
- `clink_start.cmd` — minimal startup script

## Install the plugin in Clink

1. Put `clink_ai.lua` in a scripts directory that Clink will load.

   The easiest way is to register a script directory with Clink:

   ```cmd
   clink installscripts C:\path\to\clink-scripts
   ```

   This stores the script path in the registry so Clink loads it for all installs.

2. Put `ai_bridge.py` alongside the script, or set `CLINK_AI_BRIDGE` to its actual path.

   For example:

   ```cmd
   set CLINK_AI_BRIDGE=C:\tools\clink-llm\ai_bridge.py
   ```

3. If `CLINK_AI_BRIDGE` is not set, the Lua plugin tries to find `ai_bridge.py` in the same directory as `clink_ai.lua` before falling back to a default path.

4. Start `cmd.exe` with Clink enabled.

5. Try prompts such as:

   ```cmd
   > summarize the current folder
   > explain build errors
   > what did I run last?
   > summarize !README.md!
   ```

## Special prompt commands and macros

The plugin supports a few special prompt forms for making the AI context-aware and shell-aware.

### Built-in commands

These are not normal shell commands; they are recognized by the assistant front-end and handled specially.

- `>help` — show AI usage examples
- `>reset` — reset the current conversation session
- `>debug` — print the current provider/model/session state
- `>cmd <command>` — request a shell command suggestion instead of a narrative answer

Example:

```cmd
>cmd find text files in this folder
>debug
>reset
```

### Inline command execution tokens

You can inject the output of shell commands directly into the prompt. This is useful for asking the assistant to interpret actual local command output.

Supported forms:

- `$dir$` → runs `dir` and inserts its output
- `$(git status)` → runs the command and inserts the captured output
- `$(dir /b)` → runs a command and inserts the captured output
- `>|` or `|>` style shell piping is supported conceptually for chaining a capture into a downstream command or prompt context

Examples:

```cmd
>Summarize the content of this $dir$
>What should I do next based on $(git status)
>Explain the recent repo state from $(git log --oneline -5)
>Inspect this directory and tell me what stands out: $dir$
```

The command output is trimmed to a safe size before being sent to the model so long shell output does not blow up the prompt.

### Prompt conventions

- `>` = general terminal assistant / conversational mode
- `>cmd ...` = ask for a command suggestion instead of a general answer
- `!file.txt!` = include that local file in the prompt context
- `$cmd$` and `$(cmd)` = inline command execution and output capture

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
- fallback default: `http://localhost:12349`

It resolves the model using:

- `CLINK_AI_MODEL`
- `OPENAI_MODEL`
- `LLM_MODEL`
- fallback: `local-model`

It resolves the API key using:

- `CLINK_AI_API_KEY`
- `OPENAI_API_KEY`
- fallback: `lm-studio`

Examples:

```cmd
set CLINK_AI_URL=http://localhost:12349/v1/chat/completions
set CLINK_AI_MODEL=local-model
set CLINK_AI_API_KEY=lm-studio
```

```cmd
set OPENAI_BASE_URL=http://localhost:12349
set OPENAI_MODEL=google/gemma-3-12b
set OPENAI_API_KEY=AnyKey
```

```cmd
set OLLAMA_HOST=http://localhost:12349
set LLM_MODEL=llama3.2
```

The path is not forced to one exact shape. The backend uses the provider source to decide the proper API path:

- OpenAI-compatible / LM Studio: `/v1/chat/completions`
- Ollama: `/api/chat`
- otherwise, the bridge falls back to a reasonable default

## Why the bridge is Python

Clink itself must be Lua because it is a Lua-hosted shell extension. The AI bridge does not have to be Lua; Python is a better fit for HTTP, JSON, file context, session state, command-output capture, and provider normalization.

The pattern is intentionally split:

- `clink_ai.lua` handles shell interception and route selection.
- `ai_bridge.py` handles model calls, file context, command-output injection, provider normalization, and bounded session memory.

This keeps the shell hook thin while making the model layer easier to reuse from PowerShell, bash, or other scripts.

## Conversation memory and prompt handling

The helper keeps a bounded conversation history in a local session file under `%LOCALAPPDATA%\clink-llm\chat_session.json`.

This prevents the assistant from forgetting the previous exchange and keeps the prompt window manageable. The history is trimmed to a small number of recent turns to avoid blowing the model's context window.

The bridge is designed for terminal usage, so the system prompt emphasizes short, actionable output and continued terminal context.

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

- Add richer prompt redrawing and more reliable prompt restoration after AI output.
- Add confirm/continue semantics for follow-up responses like `y`, `yes`, `no`, and `continue`.
- Add explicit chat vs command-suggestion modes (`> ...` versus `>cmd ...`).
- Add command-output capture for more shell pipelines and richer prompt macros.
- Include current git status, recent directory listing, environment summary, and selected file metadata.
- Add a reset/debug/help mode for session management.
- Add a PowerShell wrapper and bash/zsh wrapper that call the same backend contract as Clink.
- Add input validation and safer file-path handling for local file context injection.
- Add support for more provider-specific endpoints beyond OpenAI-compatible ones.
- Add result caching and a lightweight request log for repeat prompts.
- Add a non-blocking queue directory and worker model for cleaner asynchronous output.
- Add a simple plugin configuration file for default prefix, model, and backend settings.

## License

MIT
