import execjs
import json

ctx = {"foo": "bar"}
script = """
var child_process = require('child_process');
var result = child_process.execSync('echo hello').toString().trim();
result + " " + foo;
"""

def test():
    try:
        runtime = execjs.get()
        print(f"Runtime: {runtime.name}")
        
        ctx_str = json.dumps(ctx)
        wrapper = f"""
        function run(ctx) {{
            var foo = ctx.foo;
            var child_process = require('child_process');
            var result = child_process.execSync('echo hello').toString().trim();
            return result + " " + foo;
        }}
        """
        compiled = runtime.compile(wrapper)
        res = compiled.call("run", ctx)
        print(f"Result: {res}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
