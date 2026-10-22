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
                    table.insert(lines, line)
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

local function save_job(prompt, files, history)
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
        f:write("  \"prefix\": \"" .. json_escape(prefix) .. "\"\n")
        f:write("}\n")
        f:close()
    end

    return path
end

local function queue_ai_request(prompt, files, history)
    local jobfile = save_job(prompt, files, history)
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

    if prompt:lower() == "help" then
        print("AI prefix usage:")
        print("  " .. prefix .. " summarize this folder")
        print("  " .. prefix .. " explain build errors")
        print("  " .. prefix .. " what did I run last?")
        print("  " .. prefix .. " summarize !README.md!")
        return ""
    end

    local files = extract_file_refs(prompt)
    local history = get_history_text()
    return queue_ai_request(prompt, files, history)
end

clink.onfilterinput(on_filter_input)
