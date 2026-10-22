-- clink_ai.lua
-- Library-safe Clink integration.
-- This file is sourced by Clink, so do not execute anything on require.
-- It registers a filter callback and requires ai_bridge.lua as a library.

local script_dir = nil

local function get_script_dir()
	local info = debug.getinfo(1, "S")
	local source = info and info.source or ""
	if source and source:sub(1, 1) == "@" then
		source = source:sub(2)
	end
	local dir = source:match("^(.*)[\\/][^\\/]+$") or "."
	return dir
end

script_dir = get_script_dir()

if not package.path:find(script_dir, 1, true) then
	package.path = package.path .. ";" .. script_dir .. "\\?.lua"
end

local ai_bridge = require("ai_bridge")

local prefix = os.getenv("CLINK_AI_PREFIX") or "!"

local curl_path_cache = nil

local function trim(s)
	if s == nil then
		return ""
	end
	s = tostring(s)
	s = s:gsub("^%s+", "")
	s = s:gsub("%s+$", "")
	return s
end

local function shell_quote(s)
	return '"' .. tostring(s):gsub('"', '""') .. '"'
end

local function find_curl_executable()
	if curl_path_cache then
		return curl_path_cache
	end

	local f = io.popen("where curl.exe 2>nul", "r")
	if f then
		local first = f:read("*l")
		f:close()
		if first and trim(first) ~= "" then
			curl_path_cache = trim(first)
			return curl_path_cache
		end
	end

	curl_path_cache = "curl.exe"
	return curl_path_cache
end

local function safe_json_encode(data)
	local ok, cjson = pcall(require, "cjson")
	if ok and cjson and cjson.encode then
		local ok2, text = pcall(cjson.encode, data)
		if ok2 then
			return text
		end
	end

	local ok2, dkjson = pcall(require, "dkjson")
	if ok2 and dkjson and dkjson.encode then
		local ok3, text = pcall(dkjson.encode, data)
		if ok3 then
			return text
		end
	end

	return "{}"
end

local function json_decode(text)
	if not text or trim(text) == "" then
		return nil
	end

	local ok, cjson = pcall(require, "cjson")
	if ok and cjson and cjson.decode then
		local ok2, data = pcall(cjson.decode, text)
		if ok2 then
			return data
		end
	end

	local ok2, dkjson = pcall(require, "dkjson")
	if ok2 and dkjson and dkjson.decode then
		local ok3, data = pcall(dkjson.decode, text)
		if ok3 then
			return data
		end
	end

	return nil
end

local function write_text_file(path, text)
	if not path or path == "" then
		return false
	end
	local dir = path:match("^(.*)[\\/][^\\/]+$")
	if dir and dir ~= "" then
		os.execute('mkdir "' .. dir .. '" >nul 2>&1')
	end
	local f = io.open(path, "w")
	if not f then
		return false
	end
	f:write(text or "")
	f:close()
	return true
end

local function read_text_file(path)
	if not path or path == "" then
		return ""
	end
	local f = io.open(path, "r")
	if not f then
		return ""
	end
	local data = f:read("*all")
	f:close()
	return data or ""
end

local function session_file_path()
	local base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
	return base .. "\\clink-llm\\chat_session.json"
end

local function load_session_file()
	local p = session_file_path()
	local f = io.open(p, "r")
	if not f then
		return {}
	end
	local text = f:read("*all")
	f:close()
	local data = json_decode(text)
	if type(data) == "table" and data.messages then
		return data.messages
	end
	return {}
end

local function save_session_file(messages)
	local p = session_file_path()
	local dir = p:match("^(.*)[\\/][^\\/]+$")
	if dir and dir ~= "" then
		os.execute('mkdir "' .. dir .. '" >nul 2>&1')
	end
	local doc = { messages = messages or {} }
	local ok = write_text_file(p, safe_json_encode(doc))
	return ok
end

local function terminal_snapshot(limit)
	limit = tonumber(limit) or 200
	if limit <= 0 then
		return ""
	end

	if not console or not console.getnumlines or not console.getlinetext then
		return ""
	end

	local total = tonumber(console.getnumlines()) or 0
	if total <= 0 then
		return ""
	end

	local first = math.max(1, total - limit + 1)
	local lines = {}

	for i = first, total do
		local line = console.getlinetext(i)
		if line and trim(line) ~= "" then
			table.insert(lines, trim(line))
		end
	end

	return table.concat(lines, "\n")
end

local function history_snapshot(limit)
	limit = tonumber(limit) or 20
	local candidates = {
		os.getenv("CLINK_HISTORY_FILE"),
		os.getenv("CLINK_PROFILE") and (os.getenv("CLINK_PROFILE") .. "\\clink_history"),
		os.getenv("LOCALAPPDATA") and (os.getenv("LOCALAPPDATA") .. "\\clink\\clink_history"),
		os.getenv("USERPROFILE") and (os.getenv("USERPROFILE") .. "\\AppData\\Local\\clink\\clink_history"),
	}

	local seen = {}
	local out = {}

	for _, path in ipairs(candidates) do
		if path and path ~= "" then
			local f = io.open(path, "r")
			if f then
				for line in f:lines() do
					local clean = trim(line)
					if clean ~= "" and not seen[clean] then
						seen[clean] = true
						table.insert(out, clean)
					end
				end
				f:close()
			end
		end
	end

	if #out > limit then
		local start = #out - limit + 1
		local temp = {}
		for i = start, #out do
			table.insert(temp, out[i])
		end
		out = temp
	end

	return table.concat(out, "\n")
end

local function git_status_snapshot()
	local cwd = os.getenv("CD") or os.getenv("PWD") or "."
	local cmd = 'git -C "' .. cwd .. '" status --short --branch 2>nul'
	local f = io.popen(cmd, "r")
	if not f then
		return ""
	end
	local out = f:read("*all")
	f:close()
	return trim(out)
end

local function dir_snapshot()
	local f = io.popen("dir 2>nul", "r")
	if not f then
		return ""
	end
	local out = f:read("*all")
	f:close()
	return trim(out)
end

local function build_runtime()
	return {
		cwd = function()
			return os.getenv("CD") or os.getenv("PWD") or "."
		end,
		terminal = function(limit)
			return terminal_snapshot(limit or 200)
		end,
		history = function(limit)
			return history_snapshot(limit or 20)
		end,
		dir = function()
			return dir_snapshot()
		end,
		git = function()
			return git_status_snapshot()
		end,
		file_text = function(path)
			return read_text_file(path)
		end,
		http_json = function(url, payload, headers)
			local curl_path = find_curl_executable()
			local body = safe_json_encode(payload)

			local args = {
				curl_path,
				"-sS",
				"-X", "POST",
			}

			for k, v in pairs(headers or {}) do
				table.insert(args, "-H")
				table.insert(args, tostring(k) .. ": " .. tostring(v))
			end

			table.insert(args, "--data-binary")
			table.insert(args, body)
			table.insert(args, tostring(url))

			local cmd = ""
			for _, v in ipairs(args) do
				cmd = cmd .. " " .. shell_quote(v)
			end
			cmd = trim(cmd)

			local p = io.popen(cmd, "r")
			if not p then
				return { ok = false, error = "curl.exe not available" }
			end

			local out = p:read("*all")
			local close_ok = p:close()
			if close_ok == nil then
				return { ok = false, error = "curl request failed" }
			end

			return { ok = true, data = out or "" }
		end,
		log = function(msg)
			print(msg)
		end,
	}
end

local runtime = build_runtime()
local bridge = ai_bridge.new(runtime)

local function extract_prompt(line)
	local s = trim(line)
	if s == "" then
		return nil
	end
	if s:sub(1, 1) ~= prefix then
		return nil
	end
	return s:sub(#prefix + 1):gsub("^%s+", "")
end

local function expand_macros(prompt)
	local text = prompt or ""
	text = text:gsub("%$terminal%$", function()
		return runtime.terminal(200)
	end)
	text = text:gsub("%$terminal:(%d+)%$", function(n)
		return runtime.terminal(tonumber(n) or 200)
	end)
	text = text:gsub("%$history%$", function()
		return runtime.history(20)
	end)
	text = text:gsub("%$history:(%d+)%$", function(n)
		return runtime.history(tonumber(n) or 20)
	end)
	text = text:gsub("%$dir%$", function()
		return runtime.dir()
	end)
	text = text:gsub("%$git%$", function()
		return runtime.git()
	end)
	text = text:gsub("%$cwd%$", function()
		return runtime.cwd()
	end)
	text = text:gsub("%$pwd%$", function()
		return runtime.cwd()
	end)
	return text
end

local function on_filter_input(line)
	local raw = extract_prompt(line)
	if raw == nil then
		return nil
	end

	local prompt = expand_macros(raw)
	if trim(prompt) == "" then
		print("Usage: " .. prefix .. " <your question>")
		return ""
	end

	local prior_messages = {}
	local current = load_session_file()
	if type(current) == "table" and #current > 0 then
		prior_messages = current
	end

	local response = bridge.main({
		prompt = prompt,
		cwd = runtime.cwd(),
	}, {
		prior_messages = prior_messages,
	})

	if response and trim(response) ~= "" then
		print(response)
	end

	local conversation = prior_messages
	table.insert(conversation, { role = "user", content = prompt })
	table.insert(conversation, { role = "assistant", content = response or "" })
	if #conversation > 16 then
		conversation = { table.unpack(conversation, #conversation - 15, #conversation) }
	end
	save_session_file(conversation)

	return ""
end

clink.onfilterinput(on_filter_input)
