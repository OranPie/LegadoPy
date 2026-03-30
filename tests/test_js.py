import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine.analyze.analyze_url import JsCookie
from legado_engine.js import eval_js, JsExtensions
from legado_engine.models.book_source import BookSource

JS_CODE = r"""
let base_url = getArguments(source.getVariable(), 'server');
let media;
let sources = getArguments(source.getVariable(), 'source');
let disabled_sources = getArguments(source.getVariable(), 'disabled_sources');
if (String(key).startsWith("m:") || String(key).startsWith("m：")) {
    media = "漫画"
    key = key.slice(2)
} else if (String(key).startsWith("t:") || String(key).startsWith("t：")) {
    media = "听书"
    key = key.slice(2)
} else if (String(key).startsWith("d:") || String(key).startsWith("d：")) {
    media = "短剧"
    key = key.slice(2)
} else if (String(key).startsWith("x:") || String(key).startsWith("x：")) {
    media = "小说"
    key = key.slice(2)
} else {
    media = getArguments(source.getVariable(), 'media');
}
if (key.includes('@')) {
    var parts = key.split('@');
    key = parts[0];
    sources = parts[1] || sources;
}
let qtcookie = cookie.getCookie(base_url);
let op = {
    method: "GET",
    headers: {
        cookie: qtcookie
    },
};
op = JSON.stringify(op);
`${base_url}/search?title=${key}&tab=${media}&source=${sources}&page={{page}}&disabled_sources=${disabled_sources},${op}`
"""

def test():
    # Load source to get jsLib
    with open("/home/kasm-user/下载/安卓阅读app-大灰狼融合4.0(vip完全版).json", "r") as f:
        data = json.load(f)[0]
    
    source = BookSource.from_dict(data)
    
    print(f"JsLib length: {len(source.jsLib or '')}")
    if "getArguments" in (source.jsLib or ""):
        print("getArguments found in jsLib")
    else:
        print("getArguments NOT found in jsLib")
    
    bindings = {
        "source": source,
        "key": "剑来",
        "page": 1,
        "cookie": JsCookie(),
    }
    
    print("Running JS...")
    try:
        res = eval_js(JS_CODE, bindings=bindings)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test()
