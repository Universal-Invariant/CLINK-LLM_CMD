-- ai_bridge.lua
-- Generic bridge library for terminal AI prompts.
-- Shell-specific logic is intentionally kept out of here.
-- This module is safe to require from Clink.

local CJSON = nil
local M = {}

local function get_cjson()
	if CJSON then
		return CJSON
	end

	local ok, mod = pcall(require, "cjson")
	if ok and mod then
		CJSON = mod
		return CJSON
	end

	local ok2, mod2 = pcall(require, "dkjson")
	if ok2 and mod2 then
		CJSON = mod2
		return CJSON
	end

	CJSON = {
		encode = function(obj)
			return "{}"
		end,
		decode = function(_)
			return nil
		end,
	}
	return CJSON
end

local function trim(s)
	if s == nil then
		return ""
	end
	s = tostring(s)
	s = s:gsub("^%s+", "")
	s = s:gsub("%s+$", "")
	return s
end

local function safe_json_decode(text)
	if not text or trim(text) == "" then
		return nil
	end

	local mod = get_cjson()
	if mod and mod.decode then
		local ok, data = pcall(mod.decode, text)
		if ok then
			return data
		end
	end

	return nil
end

local function safe_json_encode(data)
	local mod = get_cjson()
	if mod and mod.encode then
		local ok, text = pcall(mod.encode, data)
		if ok then
			return text
		end
	end

	return "{}"
end

local function default_session_path()
	local base = os.getenv("LOCALAPPDATA") or os.getenv("USERPROFILE") or os.getcwd()
	return base .. "\\clink-llm\\chat_session.json"
end

local function load_session_state(path)
	local p = path or default_session_path()
	local f = io.open(p, "r")
	if not f then
		return {}
	end
	local text = f:read("*all")
	f:close()

	local parsed = safe_json_decode(text)
	if type(parsed) == "table" then
		if parsed.messages then
			return parsed.messages
		end
		return parsed
	end

	return {}
end

local function save_session_state(messages, path)
	local p = path or default_session_path()
	local dir = p:match("^(.*)[\\/][^\\/]+$")
	if dir and dir ~= "" then
		os.execute('mkdir "' .. dir .. '" >nul 2>&1')
	end

	local payload = { messages = messages or {} }
	local f = io.open(p, "w")
	if not f then
		return false
	end
	f:write(safe_json_encode(payload))
	f:close()
	return true
end

local function trim_session_messages(messages)
	if type(messages) ~= "table" then
		return {}
	end
	local out = {}
	for _, item in ipairs(messages) do
		if type(item) == "table" and item.role and item.content then
			local role = tostring(item.role)
			local content = tostring(item.content)
			if role == "user" and trim(content) == "" then
			else
				table.insert(out, {
					role = role,
					content = content:sub(1, 8000),
				})
			end
		end
	end

	local max_pairs = tonumber(os.getenv("CLINK_AI_MAX_HISTORY") or "8") * 2
	if #out > max_pairs then
		local start = #out - max_pairs + 1
		if start < 1 then
			start = 1
		end
		local tmp = {}
		for i = start, #out do
			table.insert(tmp, out[i])
		end
		out = tmp
	end

	return out
end

local function resolve_api_url(explicit_url)
	if explicit_url and trim(explicit_url) ~= "" then
		return trim(explicit_url)
	end

	local ordered = {
		"CLINK_AI_URL",
		"CLINK_AI_BASE_URL",
		"LMSTUDIO_API_BASE",
		"OPENAI_BASE_URL",
		"OLLAMA_HOST",
	}

	for _, name in ipairs(ordered) do
		local value = os.getenv(name)
		if value and trim(value) ~= "" then
			local v = trim(value)
			local lower = v:lower()

			if lower:find("ollama", 1, true) then
				if lower:find("/api", 1, true) then
					return v
				end
				return v .. "/api/chat"
			end

			if
				lower:find("lmstudio", 1, true)
				or lower:find("localhost:1234", 1, true)
				or lower:find("localhost:12349", 1, true)
			then
				if lower:find("/v1/chat/completions", 1, true) then
					return v
				end
				return v .. "/v1/chat/completions"
			end

			if lower:find("/chat/completions", 1, true) then
				return v
			end
			if lower:find("/api/chat", 1, true) then
				return v
			end
			if lower:find("/v1", 1, true) then
				return v .. "/chat/completions"
			end
			if lower:find("/api", 1, true) then
				return v .. "/chat"
			end
			return v .. "/v1/chat/completions"
		end
	end

	return "http://localhost:12349/v1/chat/completions"
end

local function resolve_model(explicit_model)
	if explicit_model and trim(explicit_model) ~= "" then
		return trim(explicit_model)
	end

	for _, name in ipairs({ "CLINK_AI_MODEL", "OPENAI_MODEL", "LLM_MODEL" }) do
		local value = os.getenv(name)
		if value and trim(value) ~= "" then
			return trim(value)
		end
	end

	return "local-model"
end

local function resolve_api_key(explicit_key)
	if explicit_key and trim(explicit_key) ~= "" then
		return trim(explicit_key)
	end

	for _, name in ipairs({ "CLINK_AI_API_KEY", "OPENAI_API_KEY" }) do
		local value = os.getenv(name)
		if value and trim(value) ~= "" then
			return trim(value)
		end
	end

	return "lm-studio"
end

local function build_prompt(input, runtime)
	local prompt = ""
	if type(input) == "string" then
		prompt = input
	elseif type(input) == "table" then
		prompt = input.prompt or ""
	end

	prompt = tostring(prompt or "")
	if trim(prompt) == "" then
		return ""
	end

	local cwd = ""
	if runtime and runtime.cwd then
		cwd = runtime.cwd() or ""
	end

	local history_text = ""
	if runtime and runtime.history then
		history_text = tostring(runtime.history(20) or "")
	end

	local dir_text = ""
	if runtime and runtime.dir then
		dir_text = tostring(runtime.dir() or "")
	end

	local git_text = ""
	if runtime and runtime.git then
		git_text = tostring(runtime.git() or "")
	end

	local context = {}
	if trim(history_text) ~= "" then
		table.insert(context, "Recent command history:\n" .. history_text)
	end
	if trim(dir_text) ~= "" then
		table.insert(context, "Current directory listing:\n" .. dir_text)
	end
	if trim(git_text) ~= "" then
		table.insert(context, "Git status:\n" .. git_text)
	end

	local context_block = table.concat(context, "\n\n")
	if trim(context_block) ~= "" then
		context_block = context_block .. "\n\n"
	end

	return "You are a helpful terminal assistant. Keep replies brief, actionable, and shell-aware.\n"
		.. "Current directory: "
		.. cwd
		.. "\n\n"
		.. context_block
		.. "User request: "
		.. prompt
		.. "\n"
end

function M.new(runtime)
	local R = runtime or {}
	local bridge = {}

	function bridge.load_session(path)
		return load_session_state(path)
	end

	function bridge.save_session(messages, path)
		return save_session_state(messages, path)
	end

	function bridge.trim_session(messages)
		return trim_session_messages(messages)
	end

	function bridge.build_prompt(input)
		return build_prompt(input, R)
	end

	function bridge.call_provider(prompt, opts)
		local options = opts or {}
		local url = resolve_api_url(options.api_url)
		local model = resolve_model(options.model)
		local key = resolve_api_key(options.api_key)

		local system_prompt =
			"You are a helpful terminal assistant for the Windows command line. Keep replies brief, actionable, shell-aware, and command-oriented."

		local history = {}
		if type(options.prior_messages) == "table" then
			for _, item in ipairs(options.prior_messages) do
				if type(item) == "table" and item.role and item.content then
					table.insert(history, {
						role = tostring(item.role),
						content = tostring(item.content),
					})
				end
			end
		end

		local payload = {
			model = model,
			messages = {
				{ role = "system", content = system_prompt },
			},
			temperature = 0.2,
			max_tokens = 512,
		}

		for _, msg in ipairs(history) do
			table.insert(payload.messages, msg)
		end

		table.insert(payload.messages, {
			role = "user",
			content = tostring(prompt),
		})

		local http_fn = R.http_json or nil
		if http_fn then
			local result = http_fn(url, payload, {
				["Content-Type"] = "application/json",
				["Accept"] = "application/json",
				["Authorization"] = "Bearer " .. key,
			})
			if not result or not result.ok then
				return "AI request failed: " .. tostring((result and result.error) or "unknown error")
			end

			local parsed = safe_json_decode(result.data or "")
			if type(parsed) == "table" then
				if parsed.choices and type(parsed.choices) == "table" and #parsed.choices > 0 then
					local choice = parsed.choices[1]
					if type(choice) == "table" and choice.message and type(choice.message) == "table" then
						return tostring(choice.message.content)
					end
				end

				if parsed.message and type(parsed.message) == "table" then
					return tostring(parsed.message.content or "")
				end
			end

			return "AI request failed: invalid response from provider"
		end

		return "AI request failed: runtime.http_json is required"
	end

	function bridge.main(input, opts)
		local prompt = bridge.build_prompt(input)
		if trim(prompt) == "" then
			return ""
		end

		local options = opts or {}
		options.prior_messages = options.prior_messages or {}
		return bridge.call_provider(prompt, options)
	end

	return bridge
end

return M
