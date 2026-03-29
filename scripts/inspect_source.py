import json

with open('/home/kasm-user/下载/安卓阅读app-大灰狼融合4.0(vip完全版).json', 'r') as f:
    data = json.load(f)

if isinstance(data, list):
    data = data[0]

print("--- JsLib ---")
js_lib = data.get('jsLib', '')
print(js_lib[:1000] + "\n...\n" + (js_lib[-500:] if len(js_lib) > 1500 else js_lib))

print("\n--- Search URL ---")
print(data.get('searchUrl', ''))

print("\n--- BookInfo Rule ---")
print(data.get('ruleBookInfo', {}))

