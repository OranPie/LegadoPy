import json
import sys
import traceback
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from legado_engine import BookSource, search_book, get_book_info, get_chapter_list, get_content

SOURCE_PATH = "/home/kasm-user/下载/安卓阅读app-大灰狼融合4.0(vip完全版).json"

def main():
    print(f"Loading source from {SOURCE_PATH}...")
    try:
        with open(SOURCE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"Failed to load JSON: {e}")
        return

    if isinstance(data, list):
        print(f"Found {len(data)} sources. Using the first one.")
        src_data = data[0]
    else:
        src_data = data

    source = BookSource.from_dict(src_data)
    print(f"Source: {source.bookSourceName} ({source.bookSourceUrl})")
    print(f"Variable Comment: {source.variableComment}")
    print(f"JsLib Length: {len(source.jsLib) if source.jsLib else 0}")
    if source.jsLib:
        print(f"JsLib Preview: {source.jsLib[:100]}...")

    print("\n--- Search Rules ---")
    search = source.ruleSearch
    if search:
        print(f"searchList: {search.bookList}")
        print(f"searchUrl: {search.checkKeyWord}")
    else:
        print("No Search rules found.")
    
    print("\n--- TOC Rules ---")
    toc = source.ruleToc
    if toc:
        print(f"chapterList: {toc.chapterList}")
        
        # Inject detailed logging into the TOC rule
        js_code = toc.chapterList
        if "<js>" in js_code:
            end_idx = js_code.rfind("</js>")
            suffix = js_code[end_idx+5:]
            
            debug_js = """
try {
    java.log("START TOC JS");
    java.log("Result type: " + typeof result);
    java.log("Result value: " + String(result).substring(0, 100));
    
    let res = JSON.parse(java.hexDecodeToString(result));
    java.log("Res parsed: " + JSON.stringify(res));

    if (res.method) {
        res = Object.fromEntries(
            res.body
            .replace("source", "sources")
            .split("&")
            .map((query) => query.split("="))
        );
        res.url = "";
    }
    let book_id = res.book_id;
    java.put('book_id', book_id);
    let tab = res.tab;
    let sources = res.sources;
    let url = res.url;
    let html = "";
    let proxy = getArguments(source.getVariable(), "proxy");
    java.log("Proxy: " + proxy);

    if (url != "" && proxy == "本地") {
        if (sources == '69书吧') {
            let ck69 = String(cookie.getCookie(url));
            let headers = {
                "Cookie": ck69
            };
            let op = JSON.stringify({
                "headers": headers
            });
            html = java.ajax(url + ',' + op);
        } else {
            html = java.ajax(url);
        }
        //java.log(html);
        if (html.includes("Just a moment...") && sources == '69书吧') {
            cookie.removeCookie(url);
            var x = `https://www.69shuba.com`;
            java.longToast('需要真人验证，请进入任意书籍详情页过验证');
            var s = java.startBrowserAwait(x, "需要真人验证，请进入任意书籍详情页过验证").body();

            let ck69 = String(cookie.getCookie(url));
            let headers = {
                "Cookie": ck69
            };
            let op = JSON.stringify({
                "headers": headers
            });
            //java.log(op);
            html = java.ajax(url + ',' + op);
            //java.log(html);
        }
    };
    let base_url = getArguments(source.getVariable(), "server");
    java.log("Base URL: " + base_url);

    let op = {
        method: "POST",
        body: {
            html: html
        }
    };
    op = JSON.stringify(op);
    let varia = String(book.getVariable('custom'));
    if (varia == 'null') {
        varia = '';
    }
    varia = JSON.stringify({
        'custom': varia
    });
    // varia = java.base64Encode(varia);
    java.log("Call URL: " + `${base_url}/catalog?book_id=${book_id}&source=${sources}&tab=${tab}&variable=${varia},${op}`);
    let data = java.ajax(
        `${base_url}/catalog?book_id=${book_id}&source=${sources}&tab=${tab}&variable=${varia},${op}`
    );
    java.log("Data length: " + (data ? data.length : 0));
    data;
} catch (e) {
    java.log("JS ERROR: " + e.toString());
    "";
}
"""
            toc.chapterList = f"<js>{debug_js}</js>{suffix}"
            print("Injected debug logging into TOC rule.")

        print(f"chapterName: {toc.chapterName}")
        print(f"chapterUrl: {toc.chapterUrl}")
        print(f"nextTocUrl: {toc.nextTocUrl}")
    else:
        print("No TOC rules found.")
    print("-----------------\n")

    # Search for a common keyword
    query = "剑来"
    print(f"\nSearching for '{query}'...")
    try:
        results = search_book(source, query)
    except Exception as e:
        print(f"Search failed: {e}")
        traceback.print_exc()
        return

    if not results:
        print("No results found.")
        # Try another query just in case
        query = "系统"
        print(f"Trying query '{query}'...")
        results = search_book(source, query)
        if not results:
            print("Still no results.")
            return

    print(f"Found {len(results)} results.")
    first_book = results[0].to_book()
    print(f"First result: {first_book.name} by {first_book.author}")
    print(f"URL: {first_book.bookUrl}")

    # Get book info
    print("\nFetching book info...")
    try:
        book_info = get_book_info(source, first_book)
        print(f"Intro: {str(book_info.intro)[:100]}...")
        print(f"TOC URL: {str(book_info.tocUrl)[:100]}...")
        
        # Workaround for bad TOC URL parsing
        if str(book_info.tocUrl).strip().startswith("[{"):
             print("Detected bad TOC URL (JSON dump), reverting to bookUrl...")
             book_info.tocUrl = book_info.bookUrl
             
    except Exception as e:
        print(f"Get info failed: {e}")
        traceback.print_exc()
        return

    # Get chapters
    print("\nFetching chapter list...")
    try:
        chapters = get_chapter_list(source, book_info)
        print(f"Found {len(chapters)} chapters.")
    except Exception as e:
        print(f"Get chapters failed: {e}")
        traceback.print_exc()
        return

    if not chapters:
        print("No chapters found.")
        return

    # Get content of first chapter
    first_chapter = chapters[0]
    print(f"\nFetching content for chapter 1: {first_chapter.title} ({first_chapter.url})...")
    try:
        content = get_content(source, book_info, first_chapter)
        print("Content preview:")
        print(content[:200])
    except Exception as e:
        print(f"Get content failed: {e}")
        traceback.print_exc()
        return

    print("\nAll tests passed!")

if __name__ == "__main__":
    main()
