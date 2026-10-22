-- ai_bridge.lua
-- Generic bridge layer for terminal AI prompts.
-- This module is intentionally shell-agnostic.
-- Clink/Lua should expand shell-specific macros before calling this script.

local cjson = require("cjson")

local DEFAULT_TIMEOUT = tonumber(os.getenv("CLINK_AI_TIMEOUT") or "60")
local MAX_SESSION_PAIRS = tonumber(os.getenv("CLINK_AI_MAX_HISTORY") or "8")
local MAX_MACRO_OUTPUT = tonumber(os.getenv("CLINK_AI_MAX_MACRO_OUTPUT") or "12000")
local MAX_HISTORY_LINES = tonumber(os.getenv("CLINK_AI_MAX_HISTORY_LINES") or "20")
local MAX_TERMINAL_CHARS = tonumber(os.getenv("CLINK_AI_MAX_TERMINAL_CHARS") or "20000")
local DEFAULT_MODEL = os.getenv("CLINK_AI_MODEL") or "local-model"
local DEFAULT_API_KEY = os.getenv("CLINK_AI_API_KEY") or "lm-studio"

local INJECTOR_REGISTRY = {}
local RECURSION_MARKERS = {
    "$terminal$",
    "$history$",
    "$dir$",
    "$git$",
    "$cwd$",
    "$pwd$",
    "$last$",
    "$(",
    "@(",
}

local function trim(s)
    if s == nil then return "" end
    s = tostring(s)
    s = s:gsub("^%s+", "")
    s = s:gsub("%s+$", "")
    return s
end

local function default_session_path()
    local base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
    return base .. "\\clink-llm\\chat_session.json"
end

local function default_terminal_log_path()
    local base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
    return base .. "\\clink-llm\\terminal_log.txt"
end

local function clean_url(value)
    if value == nil then return "" end
    value = trim(value)
    if value == "" then return "" end
    while value:sub(-1) == "/" and #value > 1 do
        value = value:sub(1, -2)
    end
    return value
end

local function join_url(base, path)
    base = clean_url(base)
    path = tostring(path or ""):gsub("^/+", "")
    if path == "" then return base end
    if base == "" then return path end
    return base .. "/" .. path
end

local function is_full_endpoint(value)
    local s = clean_url(value)
    if s == "" then return false end
    return s:match("/v1/") ~= nil or s:match("/api/") ~= nil or s:match("/chat/completions$") ~= nil or s:match("/api/chat$") ~= nil
end

local function resolve_api_url(explicit_url)
    if explicit_url and trim(explicit_url) ~= "" then
        return clean_url(explicit_url)
    end

    local ordered = {
        {"CLINK_AI_URL", os.getenv("CLINK_AI_URL")},
        {"CLINK_AI_BASE_URL", os.getenv("CLINK_AI_BASE_URL")},
        {"LMSTUDIO_API_BASE", os.getenv("LMSTUDIO_API_BASE")},
        {"OPENAI_BASE_URL", os.getenv("OPENAI_BASE_URL")},
        {"OLLAMA_HOST", os.getenv("OLLAMA_HOST")},
    }

    for _, item in ipairs(ordered) do
        local source_name, candidate = item[1], item[2]
        if candidate and trim(candidate) ~= "" then
            local value = clean_url(candidate)
            if is_full_endpoint(value) then
                return value
            end

            if source_name == "OLLAMA_HOST" then
                return join_url(value, "api/chat")
            end

            if value:lower():match("/v1$") then
                return join_url(value, "chat/completions")
            end
            if value:lower():match("/api$") then
                return join_url(value, "chat")
            end

            if value:lower():find("ollama", 1, true) then
                return join_url(value, "api/chat")
            end
            if value:lower():find("lmstudio", 1, true) or value:find("localhost:1234", 1, true) or value:find("localhost:12349", 1, true) then
                return join_url(value, "v1/chat/completions")
            end

            return join_url(value, "v1/chat/completions")
        end
    end

    return "http://localhost:12349/v1/chat/completions"
end

local function resolve_model(explicit_model)
    if explicit_model and trim(explicit_model) ~= "" then
        return trim(explicit_model)
    end

    local names = {"CLINK_AI_MODEL", "OPENAI_MODEL", "LLM_MODEL"}
    for _, name in ipairs(names) do
        local value = os.getenv(name)
        if value and trim(value) ~= "" then
            return trim(value)
        end
    end

    return DEFAULT_MODEL
end

local function resolve_api_key(explicit_key)
    if explicit_key and trim(explicit_key) ~= "" then
        return trim(explicit_key)
    end

    local names = {"CLINK_AI_API_KEY", "OPENAI_API_KEY"}
    for _, name in ipairs(names) do
        local value = os.getenv(name)
        if value and trim(value) ~= "" then
            return trim(value)
        end
    end

    return DEFAULT_API_KEY
end

local function should_record_prompt_text(text)
    if text == nil then return false end
    local value = trim(tostring(text))
    if value == "" then return false end
    local lower = value:lower()

    if lower:sub(1, 1) == ">" then
        return false
    end

    for _, marker in ipairs(RECURSION_MARKERS) do
        if lower:find(marker:lower(), 1, true) then
            return false
        end
    end

    return true
end

local function dump_json(data)
    return cjson.encode(data)
end

local function load_json_file(path)
    local f = io.open(path, "r", "rb")
    if not f then return nil end
    local content = f:read("*all")
    f:close()
    local ok, decoded = pcall(cjson.decode, content)
    if ok then return decoded end
    return nil
end

local function save_json_file(path, obj)
    local dir = path:match("^(.*)[\\/][^\\/]+$")
    if dir and not path:match("^%w:") then
        -- relative path is just path; skip mkdir if not needed
    end

    local parent = path:match("^(.*)[\\/][^\\/]+$")
    if parent and parent ~= "" then
        os.execute('mkdir "' .. parent .. '" >nul 2>&1')
    end

    local f = io.open(path, "w", "wb")
    if not f then return false end
    f:write(cjson.encode(obj))
    f:close()
    return true
end

local function load_session_state(path)
    local session_path = path or default_session_path()
    local ok, data = pcall(load_json_file, session_path)
    if not ok or data == nil then
        return {}
    end

    if type(data) == "table" then
        if data.messages then
            return data.messages
        end
        if type(data) == "table" then
            return data
        end
    end

    return {}
end

local function save_session_state(messages, path)
    local session_path = path or default_session_path()
    local parent = session_path:match("^(.*)[\\/][^\\/]+$")
    if parent and parent ~= "" then
        os.execute('mkdir "' .. parent .. '" >nul 2>&1')
    end

    local doc = { messages = messages or {} }
    return save_json_file(session_path, doc)
end

local function dedupe_recent_messages(messages)
    if type(messages) ~= "table" then return {} end

    local filtered = {}
    local last_user_text = nil

    for _, item in ipairs(messages) do
        if type(item) == "table" then
            local role = item.role
            local content = item.content
            if role == "user" and type(content) == "string" then
                local candidate = trim(content)
                if candidate == last_user_text then
                    goto continue
                end
                last_user_text = candidate
            end
            table.insert(filtered, item)
        end
        ::continue::
    end

    return filtered
end

local function trim_session_messages(messages)
    if type(messages) ~= "table" then return {} end

    local trimmed = {}
    for _, item in ipairs(messages) do
        if type(item) == "table" and item.role and item.content then
            local content = tostring(item.content):sub(1, 8000)
            if item.role == "user" and not should_record_prompt_text(content) then
                goto continue
            end
            table.insert(trimmed, { role = item.role, content = content })
        end
        ::continue::
    end

    if #trimmed > (MAX_SESSION_PAIRS * 2) then
        trimmed = { table.unpack(trimmed, math.max(1, #trimmed - (MAX_SESSION_PAIRS * 2) + 1), #trimmed) }
    end

    return dedupe_recent_messages(trimmed)
end

local function read_text_file(path, max_chars)
    max_chars = max_chars or 20000
    local f = io.open(path, "r", "rb")
    if not f then return "" end
    local content = f:read(max_chars)
    f:close()
    return content or ""
end

local function split_files(raw)
    if raw == nil then return {} end
    local items = {}
    for part in string.gmatch(raw, "[^,]+") do
        local value = trim(part)
        if value ~= "" then
            table.insert(items, value)
        end
    end
    return items
end

local function to_temp_file(content)
    local p = os.tmpname()
    local f = io.open(p, "wb")
    if not f then return nil end
    f:write(content)
    f:close()
    return p
end

local function http_post_json(url, headers, payload)
    local tmp = to_temp_file(payload)
    if not tmp then
        return nil, "failed to create temp file"
    end

    local header_args = ""
    for k, v in pairs(headers or {}) do
        header_args = header_args .. ' -H "' .. tostring(k) .. ': ' .. tostring(v) .. '"'
    end

    local escaped_url = tostring(url):gsub('"', '\\"')
    local cmd = 'curl.exe -sS -X POST ' .. header_args .. ' -d @"' .. tmp .. '" "' .. escaped_url .. '"'
    local out = io.popen(cmd, "r")
    if not out then
        os.remove(tmp)
        return nil, "curl.exe not available"
    end

    local result = out:read("*all")
    local status = out:close()
    os.remove(tmp)

    if status == nil then
        return nil, "curl request failed"
    end

    return result, nil
end

local function call_provider(prompt, api_url, model_name, api_key, prior_messages, mode)
    local url = resolve_api_url(api_url)
    local model = resolve_model(model_name)
    local key = resolve_api_key(api_key)

    local mode_name = (mode or "chat"):lower()
    local system_text
    if mode_name == "cmd" then
        system_text = "You are a shell command suggestion assistant for Windows cmd.exe. Prefer concise, valid commands and do not invent unsupported flags."
    else
        system_text = "You are a helpful terminal assistant for the Windows command line. Keep replies brief, actionable, shell-aware, and command-oriented."
    end

    local messages = {
        { role = "system", content = system_text }
    }

    if type(prior_messages) == "table" then
        for _, item in ipairs(prior_messages) do
            if type(item) == "table" and item.role and item.content then
                table.insert(messages, { role = item.role, content = tostring(item.content) })
            end
        end
    end

    table.insert(messages, { role = "user", content = tostring(prompt) })

    local payload = {
        model = model,
        messages = messages,
        temperature = 0.2,
        max_tokens = 512,
    }

    local json_body = cjson.encode(payload)
    local headers = {
        ["Content-Type"] = "application/json",
        ["Accept"] = "application/json",
        ["Authorization"] = "Bearer " .. key,
    }

    local result, err = http_post_json(url, headers, json_body)
    if err then
        return "AI request failed: " .. err, messages
    end

    local ok, parsed = pcall(cjson.decode, result)
    if ok and type(parsed) == "table" then
        if parsed.choices and type(parsed.choices) == "table" and #parsed.choices > 0 then
            local choice = parsed.choices[1]
            if type(choice) == "table" and choice.message and type(choice.message) == "table" then
                return choice.message.content, messages
            end
        end
        if parsed.message and type(parsed.message) == "table" then
            return parsed.message.content or "", messages
        end
        return cjson.encode(parsed), messages
    end

    return "AI request failed: invalid response", messages
end

local function resolve_prompt_from_job(job)
    if type(job) ~= "table" then return "" end
    local prompt = job.prompt or ""
    if prompt == "" then
        return ""
    end
    return tostring(prompt)
end

local function build_user_message(job)
    local cwd = job.cwd or os.getcwd()
    local history = tostring(job.history or "")
    local prompt = resolve_prompt_from_job(job)
    local files = job.files or {}
    local file_section = ""
    local file_snippets = {}

    for _, file in ipairs(files) do
        local text = read_text_file(file, 20000)
        if text and trim(text) ~= "" then
            table.insert(file_snippets, "\n--- FILE: " .. tostring(file) .. " ---\n" .. text:sub(1, 20000) .. "\n--- END FILE ---\n")
        end
    end

    if #file_snippets > 0 then
        file_section = table.concat(file_snippets, "\n")
    end

    local history_section = ""
    if trim(history) ~= "" then
        history_section = "\nRecent command history:\n" .. history .. "\n"
    end

    local mode = (job.mode or "chat"):lower()
    local assistant_mode
    if mode == "cmd" then
        assistant_mode = "You are a shell command suggestion assistant. Return only a concise, valid command or a short explanation with the command first."
    else
        assistant_mode = "You are a helpful terminal assistant. Keep replies brief, actionable, and shell-aware."
    end

    return assistant_mode ..
        "\nCurrent directory: " .. tostring(cwd) .. "\n" ..
        history_section ..
        file_section ..
        "\nUser request: " .. prompt .. "\n"
end

local function build_prompt_from_args(args)
    local files = {}
    if args.files then
        for _, item in ipairs(args.files) do
            for _, file in ipairs(split_files(item)) do
                table.insert(files, file)
            end
        end
    end

    local file_section = ""
    local file_snippets = {}

    for _, file in ipairs(files) do
        local text = read_text_file(file, 20000)
        if text and trim(text) ~= "" then
            table.insert(file_snippets, "\n--- FILE: " .. tostring(file) .. " ---\n" .. text:sub(1, 20000) .. "\n--- END FILE ---\n")
        end
    end

    if #file_snippets > 0 then
        file_section = table.concat(file_snippets, "\n")
    end

    local history_section = ""
    if args.history and trim(args.history) ~= "" then
        history_section = "\nRecent command history:\n" .. tostring(args.history) .. "\n"
    end

    local cwd = args.cwd or os.getcwd()
    local prompt = tostring(args.prompt or "")
    local mode = (args.mode or "chat"):lower()

    local assistant_mode
    if mode == "cmd" then
        assistant_mode = "You are a shell command suggestion assistant. Return only a concise, valid command or a short explanation with the command first."
    else
        assistant_mode = "You are a helpful terminal assistant. Keep replies brief, actionable, and shell-aware."
    end

    return assistant_mode ..
        "\nCurrent directory: " .. tostring(cwd) .. "\n" ..
        history_section ..
        file_section ..
        "\nUser request: " .. prompt .. "\n"
end

local function parse_cli_args()
    local args = {
        prompt = "",
        cwd = nil,
        history = nil,
        files = {},
        api_url = nil,
        model = nil,
        api_key = nil,
        session_file = nil,
        mode = "chat",
        reset_session = false,
        debug = false,
        job = nil,
    }

    local i = 1
    while i <= #arg do
        local a = arg[i]
        if a == "--job" then
            args.job = arg[i + 1]
            i = i + 2
        elseif a == "--prompt" then
            args.prompt = arg[i + 1] or ""
            i = i + 2
        elseif a == "--cwd" then
            args.cwd = arg[i + 1]
            i = i + 2
        elseif a == "--history" then
            args.history = arg[i + 1] or ""
            i = i + 2
        elseif a == "--files" then
            args.files = {}
            i = i + 1
            while i <= #arg and arg[i] and arg[i]:sub(1, 2) ~= "--" do
                table.insert(args.files, arg[i])
                i = i + 1
            end
        elseif a == "--api-url" then
            args.api_url = arg[i + 1]
            i = i + 2
        elseif a == "--model" then
            args.model = arg[i + 1]
            i = i + 2
        elseif a == "--api-key" then
            args.api_key = arg[i + 1]
            i = i + 2
        elseif a == "--session-file" then
            args.session_file = arg[i + 1]
            i = i + 2
        elseif a == "--mode" then
            args.mode = arg[i + 1] or "chat"
            i = i + 2
        elseif a == "--reset-session" then
            args.reset_session = true
            i = i + 1
        elseif a == "--debug" then
            args.debug = true
            i = i + 1
        else
            i = i + 1
        end
    end

    return args
end

local function main()
    local args = parse_cli_args()

    if args.job then
        local ok, job = pcall(load_json_file, args.job)
        if not ok or type(job) ~= "table" then
            print("Failed to read job: " .. tostring(args.job))
            return 1
        end

        local session_file = args.session_file or job.session_file or default_session_path()
        local prior_messages = trim_session_messages(load_session_state(session_file))
        local mode = (job.mode or args.mode or "chat"):lower()

        if args.reset_session then
            save_session_state({}, session_file)
            print("Session reset.")
            return 0
        end

        if args.debug then
            print("CLINK-LLM debug")
            print("cwd: " .. tostring(job.cwd or os.getcwd()))
            print("session_file: " .. tostring(session_file))
            print("provider_url: " .. resolve_api_url())
            print("model: " .. resolve_model())
            print("api_key_present: " .. tostring(resolve_api_key() ~= ""))
            return 0
        end

        local prompt = build_user_message(job)
        local result, messages = call_provider(prompt, args.api_url, args.model, args.api_key, prior_messages, mode)
        local convo = prior_messages
        if type(convo) ~= "table" then convo = {} end
        table.insert(convo, { role = "user", content = prompt })
        table.insert(convo, { role = "assistant", content = result })

        save_session_state(trim_session_messages(convo), session_file)

        print("")
        print("AI response:")
        print(string.rep("-", 60))
        print(result)
        print(string.rep("-", 60))
        return 0
    end

    local session_file = args.session_file or default_session_path()
    local prior_messages = trim_session_messages(load_session_state(session_file))
    local mode = (args.mode or "chat"):lower()

    if args.reset_session then
        save_session_state({}, session_file)
        print("Session reset.")
        return 0
    end

    if args.debug then
        print("CLINK-LLM debug")
        print("cwd: " .. tostring(args.cwd or os.getcwd()))
        print("session_file: " .. tostring(session_file))
        print("provider_url: " .. resolve_api_url())
        print("model: " .. resolve_model())
        print("api_key_present: " .. tostring(resolve_api_key() ~= ""))
        return 0
    end

    local prompt = build_prompt_from_args(args)
    local result, messages = call_provider(prompt, args.api_url, args.model, args.api_key, prior_messages, mode)

    local convo = prior_messages
    if type(convo) ~= "table" then convo = {} end
    table.insert(convo, { role = "user", content = prompt })
    table.insert(convo, { role = "assistant", content = result })

    save_session_state(trim_session_messages(convo), session_file)

    print("")
    print("AI response:")
    print(string.rep("-", 60))
    print(result)
    print(string.rep("-", 60))
    return 0
end

return main()
