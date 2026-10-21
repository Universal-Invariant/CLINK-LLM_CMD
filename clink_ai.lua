-- clink_ai.lua
-- Minimal Clink hook: lines beginning with ">" are intercepted and
-- handed to a Python bridge for LLM processing.
--
-- This makes the shell itself stay simple. The actual AI logic lives in
-- a helper script so it can be reused from other shells later.

local prefix = os.getenv("CLINK_AI_PREFIX") or ">"
local bridge = os.getenv("CLINK_AI_BRIDGE") or "C:\\tools\\clink-llm\\ai_bridge.py"

local function trim(s)
    if s == nil then return "" end
    s = s:gsub("^%s+", "")
    s = s:gsub("%s+$", "")
    return s
end

local function escape_for_cmd(s)
    -- Very rough escaping for Windows command line.
    -- Good enough for a personal helper script.
    return (s:gsub('"', '\\"'))
end

local function ensure_dir(path)
    local ok = os.execute('mkdir "' .. path .. '" >nul 2>&1')
    return ok
end

local function save_job(prompt)
    local appdata = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or "."
    local dir = appdata .. "\\clink-llm"
    ensure_dir(dir)
    local jobs = dir .. "\\jobs"
    ensure_dir(jobs)

    local timestamp = os.date("%Y%m%d-%H%M%S")
    local file = jobs .. "\\job-" .. timestamp .. ".json"

    -- Build a tiny JSON payload.
    -- We do not try to be perfect here; the Python bridge can be extended.
    local cwd = os.getenv("CD") or os.getenv("PWD") or "."
    local history = ""
    local f = io.open(file, "w")
    if f then
        f:write('{')
        f:write(string.format('"prompt":"%s",', escape_for_cmd(prompt)))
        f:write(string.format('"cwd":"%s",', escape_for_cmd(cwd)))
        f:write(string.format('"prefix":"%s",', escape_for_cmd(prefix)))
        f:write(string.format('"history":"%s"', escape_for_cmd(history)))
        f:write('}')
        f:close()
    end

    return file
end

local function queue_ai_request(prompt)
    local jobfile = save_job(prompt)

    local command = string.format(
        'start "" /b cmd /c python "%s" --job "%s"',
        bridge,
        jobfile
    )

    -- We intentionally do not block here.
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
        print("  " .. prefix .. " read !somefile.txt!")
        return ""
    end

    return queue_ai_request(prompt)
end

clink.onfilterinput(on_filter_input)
