-- clink_ai.lua
-- Thin Clink hook: lines beginning with the configured prefix are intercepted
-- and passed to a helper script for context gathering and LLM processing.

local prefix = os.getenv("CLINK_AI_PREFIX") or ">"

local function default_bridge_path()
    local info = debug.getinfo(1, "S")
    local source = info and info.source or ""
    if source and source:sub(1, 1) == "@" then
        source = source:sub(2)
    end

    local dir = source:match("^(.*)[\\/][^\\/]+$") or "."
    local candidate = dir .. "\\ai_bridge.py"
    local f = io.open(candidate, "r")
    if f then
        f:close()
        return candidate
    end

    return "C:\\tools\\clink-llm\\ai_bridge.py"
end

local bridge = os.getenv("CLINK_AI_BRIDGE") or default_bridge_path()
local session_file = os.getenv("CLINK_AI_SESSION_FILE") or (os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or ".") .. "\\clink-llm\\chat_session.json"
local terminal_log = os.getenv("CLINK_AI_TERMINAL_LOG") or (os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or ".") .. "\\clink-llm\\terminal_log.txt"

local function trim(s)
    if s == nil then return "" end
    s = s:gsub("^%s+", "")
    s = s:gsub("%s+$", "")
    return s
end

local function json_escape(s)
    if s == nil then return "" end
    s = s:gsub("\\", "\\\\")
    s = s:gsub('"', '\\"')
    s = s:gsub("\n", "\\n")
    s = s:gsub("\r", "\\r")
    s = s:gsub("\t", "\\t")
    return s
end

local function write_json_array(f, arr)
    f:write("[")
    for i, v in ipairs(arr) do
        if i > 1 then
            f:write(",")
        end
        f:write('"' .. json_escape(v) .. '"')
    end
    f:write("]")
end

local function ensure_dir(path)
    local ok = os.execute('mkdir "' .. path .. '" >nul 2>&1')
    return ok
end

local function is_prompt_like(text)
    local s = trim(text or "")
    if s == "" then
        return false
    end
    if s:sub(1, 1) == ">" then
        return true
    end
    if s:find("$terminal$") or s:find("$history$") or s:find("$dir$") or s:find("$(") or s:find("@(") then
        return true
    end
    return false
end

local function append_terminal_log(entry)
    if not entry or entry == "" then
        return
    end
    if is_prompt_like(entry) then
        return
    end

    local dir = terminal_log:match("^(.*)[\\/][^\\/]+$") or "."
    ensure_dir(dir)
    local f = io.open(terminal_log, "a")
    if f then
        f:write(entry .. "\n")
        f:close()
    end
end

local function record_shell_output(raw)
    local entry = trim(raw or "")
    if entry == "" then
        return
    end
    if is_prompt_like(entry) then
        return
    end
    append_terminal_log(entry)
end

local function get_history_text()
    local candidates = {
        os.getenv("CLINK_HISTORY_FILE"),
        os.getenv("CLINK_PROFILE") and (os.getenv("CLINK_PROFILE") .. "\\clink_history"),
        os.getenv("LOCALAPPDATA") and (os.getenv("LOCALAPPDATA") .. "\\clink\\clink_history"),
        os.getenv("USERPROFILE") and (os.getenv("USERPROFILE") .. "\\AppData\\Local\\clink\\clink_history"),
    }

    for _, p in ipairs(candidates) do
        if p and p ~= "" then
            local f = io.open(p, "r")
            if f then
                local lines = {}
                for line in f:lines() do
                    local clean = trim(line)
                    if clean ~= "" and not is_prompt_like(clean) then
                        table.insert(lines, clean)
                    end
                end
                f:close()

                local start_index = math.max(1, #lines - 25)
                local selected = {}
                for i = start_index, #lines do
                    table.insert(selected, lines[i])
                end
                if #selected > 0 then
                    return table.concat(selected, "\n")
                end
            end
        end
    end

    return ""
end

local function extract_file_refs(text)
    local refs = {}
    for file in text:gmatch("!(.-)!") do
        table.insert(refs, file)
    end
    return refs
end

local function command_mode_for(prompt)
    local s = trim(prompt)
    local lower = s:lower()

    if lower == "help" or lower:sub(1, 5) == "help:" then
        return "help"
    end
    if lower == "reset" then
        return "reset"
    end
    if lower == "debug" then
        return "debug"
    end
    if lower:sub(1, 4) == "cmd " then
        return "cmd"
    end
    return "chat"
end

local function save_job(prompt, files, history, mode)
    local appdata = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or "."
    local dir = appdata .. "\\clink-llm"
    ensure_dir(dir)
    local jobs = dir .. "\\jobs"
    ensure_dir(jobs)

    local timestamp = os.date("%Y%m%d-%H%M%S")
    local path = jobs .. "\\job-" .. timestamp .. ".json"

    local f = io.open(path, "w")
    if f then
        f:write("{\n")
        f:write("  \"prompt\": \"" .. json_escape(prompt) .. "\",\n")
        f:write("  \"cwd\": \"" .. json_escape(os.getenv("CD") or os.getenv("PWD") or ".") .. "\",\n")
        f:write("  \"history\": \"" .. json_escape(history or "") .. "\",\n")
        f:write("  \"session_file\": \"" .. json_escape(session_file) .. "\",\n")
        f:write("  \"files\": ")
        write_json_array(f, files or {})
        f:write(",\n")
        f:write("  \"mode\": \"" .. json_escape(mode or "chat") .. "\",\n")
        f:write("  \"prefix\": \"" .. json_escape(prefix) .. "\"\n")
        f:write("}\n")
        f:close()
    end

    return path
end

local function queue_ai_request(prompt, files, history, mode)
    local mode_value = mode or "chat"
    local jobfile = save_job(prompt, files, history, mode_value)

    if mode_value == "reset" then
        local command = string.format('python "%s" --job "%s" --reset-session', bridge, jobfile)
        os.execute(command)
        print("[AI] session reset")
        return ""
    end

    if mode_value == "debug" then
        local command = string.format('python "%s" --job "%s" --debug', bridge, jobfile)
        os.execute(command)
        print("[AI] debug info")
        return ""
    end

    local command = string.format(
        'python "%s" --job "%s"',
        bridge,
        jobfile
    )
    os.execute(command)
    print("[AI] queued")
    return ""
end

local function parse_ai_line(line)
    local s = trim(line)
    if s == "" then
        return nil
    end

    if s:sub(1, 1) ~= prefix then
        return nil
    end

    local rest = s:sub(#prefix + 1)
    rest = rest:gsub("^%s+", "")
    return rest
end

local function on_filter_input(line)
    local prompt = parse_ai_line(line)
    if prompt == nil then
        return nil
    end

    if prompt == "" then
        print("Usage: " .. prefix .. " <your question>")
        return ""
    end

    local mode = command_mode_for(prompt)
    if mode == "help" then
        print("AI prefix usage:")
        print("  " .. prefix .. " summarize this folder")
        print("  " .. prefix .. " explain build errors")
        print("  " .. prefix .. " what did I run last?")
        print("  " .. prefix .. " summarize !README.md!")
        print("  " .. prefix .. " $dir$")
        print("  " .. prefix .. " $history$")
        print("  " .. prefix .. " $terminal$")
        print("  " .. prefix .. " $(git status)")
        print("  " .. prefix .. " @(registered_python_function(args))")
        print("  " .. prefix .. " >cmd find text files")
        print("  " .. prefix .. " >reset")
        print("  " .. prefix .. " >debug")
        print("  " .. prefix .. "help:clink:keys What command lists recent directory output?")
        return ""
    end

    if mode == "reset" then
        local files = {}
        local history = get_history_text()
        return queue_ai_request("reset", files, history, "reset")
    end

    if mode == "debug" then
        local files = {}
        local history = get_history_text()
        return queue_ai_request("debug", files, history, "debug")
    end

    if mode == "cmd" then
        local command_text = trim(prompt:sub(5))
        local files = extract_file_refs(command_text)
        local history = get_history_text()
        return queue_ai_request(command_text, files, history, "cmd")
    end

    local files = extract_file_refs(prompt)
    local history = get_history_text()
    return queue_ai_request(prompt, files, history, "chat")
end

clink.onfilterinput(on_filter_input)
