# CLINK-LLM_CMD

A lightweight Clink frontend for routing inline command prompts to an LLM backend.

The shell-side hook intercepts lines beginning with a configurable prefix (default: `>`), captures useful context (cwd, recent history, file refs, and shell state), and prevents the original raw line from being executed by `cmd.exe`. It then hands the job off to a Python helper that calls an OpenAI-compatible or provider-specific endpoint.

Files in this repo:

- `clink_ai.lua` — Clink Lua plugin
- `ai_bridge.py` — Python backend used by Clink and other terminals
- `clink_start.cmd` — minimal startup script

## Install the plugin in Clink

1. Put `clink_ai.lua` in a scripts directory that Clink will load.

   The easiest way is to register a script directory with Clink:

   ```cmd
   clink installscripts C:\path\to\clink-scripts
   ```

   This stores the script path in the registry so Clink loads it for all installs.

2. Put `ai_bridge.py` alongside the script, or set `CLINK_AI_BRIDGE` to its actual path.

   Example:

   ```cmd
   set CLINK_AI_BRIDGE=C:\tools\clink-llm\ai_bridge.py
   ```

3. If `CLINK_AI_BRIDGE` is not set, the Lua plugin tries to find `ai_bridge.py` in the same directory as `clink_ai.lua` before falling back to a default path.

4. Start `cmd.exe` with Clink enabled.

5. Try prompts such as:

   ```cmd
   > summarize this folder $dir$
   > explain build errors $terminal$
   > what did I run last? $history$
   > summarize !README.md!
   > what should I do with $(git status)
   ```

## Special prompt commands and macros

The plugin supports a few special prompt forms for making the AI context-aware and shell-aware.

### Built-in commands

These are not normal shell commands; they are recognized by the front-end and handled specially.

- `>help` — show AI usage examples
- `>reset` — reset the current conversation session
- `>debug` — print the current provider/model/session state
- `>cmd <command>` — request a shell command suggestion instead of a general answer
- `>help:clink:keys ...` — future help namespace pattern for terminal knowledge lookup

Example:

```cmd
>help
>cmd find text files in this folder
>debug
>reset
>help:clink:keys What command lists recent directory output?
```

### Prompt macros and built-in shell context

These are the main prompt macro forms we use to inject real shell context into the model prompt.

- `$dir$` — current directory listing (`dir`)
- `$history$` — recent command history
- `$terminal$` — recent terminal/build output or captured console context
- `$git$` or `$gitstatus$` — `git status --short --branch`
- `$cwd$` or `$pwd$` — current working directory
- `$last$` or `$lastcmd$` — most recent command from the environment if available
- `$(git status)` — explicitly run a command and insert its output into the prompt
- `$(git log --oneline -5)` — run an arbitrary command and capture its output
- `!file.txt!` — include a file in the prompt context
- `@(registered_python_function(args))` — custom injector hook for a Python function registered by the user

Examples:

```cmd
> summarize the contents of the current folder $dir$
> explain build errors in this terminal $terminal$
> what did I run last? $history$
> summarize !README.md!
> what do I need to do next based on $(git status)
> which command lists recent directory output? help:clink:keys
> @(my_injector("Z:\"))
```

The shell output is trimmed to a safe size before being sent to the model so long command output does not blow up the prompt.

### Custom injectors

The system is designed to stay generic and not just Clink-specific. A user can register custom Python injectors that return text to be embedded into the prompt. The syntax is:

```text
@(registered_python_function(args))
```

This is resolved by a Python registry in `ai_bridge.py`.

For example, a user can register a Python function like this:

```python
from ai_bridge import register_injector


def my_injector(args_text="", **kwargs):
    return "some extracted context"


register_injector("my_injector", my_injector)
```

The injector can also be loaded from a custom Python file via the environment variable:

```cmd
set CLINK_AI_INJECTOR_PATHS=C:\path\to\my_injectors.py
```

The module may define either:

- `INJECTORS = { "my_injector": my_injector }`
- or `injectors = { "my_injector": my_injector }`

This allows the prompt layer to stay generic while users add domain-specific tools for their own environment.

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

Clink itself must be Lua because it is a Lua-hosted shell extension. The AI bridge does not have to be Lua; Python is a better fit for HTTP, JSON, file context, session state, command-output capture, shell macros, and provider normalization.

The pattern is deliberately split:

- `clink_ai.lua` handles shell interception and route selection.
- `ai_bridge.py` handles model calls, shell context injection, prompt macro expansion, custom injectors, provider normalization, and bounded session memory.

This keeps the shell hook thin while making the model layer easier to reuse from PowerShell, bash, or other scripts.

## Conversation memory and prompt handling

The helper keeps a bounded conversation history in a local session file under `%LOCALAPPDATA%\clink-llm\chat_session.json`.

This prevents the assistant from forgetting the previous exchange and keeps the prompt window manageable. The history is trimmed to a small number of recent turns to avoid blowing the model's context window.

The bridge is designed for terminal usage, so the system prompt emphasizes short, actionable output and continued terminal context.

## Generic design goal

This plugin is intentionally generic enough to be useful outside of Clink. The same backend logic can be reused from:

- Clink
- PowerShell
- bash and zsh
- other terminal wrappers or custom assistants

The generic contract is:

- the front-end intercepts user input
- the backend expands macros and injectors
- the backend sends a prompt to an LLM provider
- the terminal frontend displays a concise answer

This keeps the project useful even if the shell host changes.

## Example terminal workflows

```cmd
> summarize the current folder $dir$
> explain errors in this build log $terminal$
> what should I do now based on $(git status)
> summarize !README.md!
>cmd find large files in this folder
>help:clink:keys Show recent directory output.
```

## Future enhancements

Planned follow-up improvements for this project:

- Add a real help directory / RAG layer for terminal commands and manuals.
- Add a namespace system like `help:clink:keys`, `help:git:status`, and `help:python:venv`.
- Add richer prompt redrawing and more reliable prompt restoration after AI output.
- Add explicit confirm/continue semantics for follow-up responses like `y`, `yes`, `no`, and `continue`.
- Add command-output capture for additional shell pipelines and richer prompt macros.
- Include current git status, recent directory listing, environment summary, and selected file metadata.
- Add a reset/debug/help mode for session management.
- Add a PowerShell wrapper and bash/zsh wrapper that call the same backend contract as Clink.
- Add input validation and safer file-path handling for local file context injection.
- Add support for more provider-specific endpoints beyond OpenAI-compatible ones.
- Add result caching and a lightweight request log for repeat prompts.
- Add a non-blocking queue directory and worker model for cleaner asynchronous output.
- Add a simple plugin configuration file for default prefix, model, and backend settings.
- Add a general-purpose help corpus so the assistant can answer things like “What command lists the recent directory output?” without the user needing to know the exact command.

## License

MIT
