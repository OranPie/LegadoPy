import re

_JS_PATTERN = re.compile(
    r"@js:([\s\S]*?)(?=@@|@CSS:|@XPath:|@Json:|$)"
    r"|<js>([\s\S]*?)</js>"
    r"|^js[:\s]([\s\S]*)$",
    re.IGNORECASE,
)

text = 'js\nlet base_url = getArguments(source.getVariable(), \'server\');\nlet media;\nlet sources = getArguments(source.getVariable(), \'source\');\nlet disabled_sources = getArguments(source.getVariable(), \'disabled_sources\');\nif (String(key).startsWith("m:") || String(key).startsWith("m：")) {\n    media = "漫画"\n    key = key.slice(2)\n} else if (String(key).startsWith("t:") || String(key).startsWith("t：")) {\n    media = "听书"\n    key = key.slice(2)\n} else if (String(key).startsWith("d:") || String(key).startsWith("d：")) {\n    media = "短剧"\n    key = key.slice(2)\n} else if (String(key).startsWith("x:") || String(key).startsWith("x：")) {\n    media = "小说"\n    key = key.slice(2)\n} else {\n    media = getArguments(source.getVariable(), \'media\');\n}\nif (key.includes(\'@\')) {\n    var parts = key.split(\'@\');\n    key = parts[0];\n    sources = parts[1] || sources;\n}\nlet qtcookie = cookie.getCookie(base_url);\nlet op = {\n    method: "GET",\n    headers: {\n        cookie: qtcookie\n    },\n};\nop = JSON.stringify(op);\n`${base_url}/search?title=${key}&tab=${media}&source=${sources}&page={{page}}&disabled_sources=${disabled_sources},${op}`\n/js'

print(f"Testing regex on: {text[:50]}...")
matches = list(_JS_PATTERN.finditer(text))
print(f"Matches found: {len(matches)}")
for m in matches:
    print(f"Match: {m.group(0)[:50]}...")
    print(f"Group 1: {m.group(1)}")
    print(f"Group 2: {m.group(2)}")
    print(f"Group 3: {m.group(3)}")
