"""ExecJS (Node.js) backend for JavaScript evaluation."""
from __future__ import annotations
import base64
import json
import os
import re
import threading
from typing import Any, Dict, Optional

from ..engine import resolve_engine
from ..exceptions import UnsupportedHeadlessOperation


_EXECJS_WRAPPER = r"""
function run(ctx) {
    var child_process = require('child_process');
    var crypto = require('crypto');

    // ------------------------------------------------------------------
    // Polyfills
    // ------------------------------------------------------------------

    var fs = require('fs');
    var logFile = '/tmp/js_engine.log';
    
    function logToFile(msg) {
        try {
            fs.appendFileSync(logFile, msg + '\n');
        } catch (e) {}
    }

    function createBodyWrapper(text) {
        var value = text == null ? "" : String(text);
        return {
            string: function() { return value; },
            toString: function() { return value; },
            valueOf: function() { return value; }
        };
    }

    function createHeadersWrapper(headers, mutable) {
        var backing = headers || {};
        return {
            _backing: backing,
            get: function(key) {
                var lookup = String(key || "").toLowerCase();
                for (var name in backing) {
                    if (String(name).toLowerCase() === lookup) {
                        return backing[name];
                    }
                }
                return null;
            },
            put: function(key, value) {
                if (mutable) {
                    backing[String(key)] = value == null ? "" : String(value);
                }
            },
            putAll: function(other) {
                if (!mutable || !other) return;
                var source = other._backing || other;
                for (var name in source) {
                    if (typeof source[name] !== 'function') {
                        backing[String(name)] = source[name] == null ? "" : String(source[name]);
                    }
                }
            },
            toJSON: function() { return backing; }
        };
    }

    function unwrapBinary(value) {
        if (!value) return value;
        if (value._legado_type === 'ByteArray' && value.base64 != null) {
            return Buffer.from(String(value.base64), 'base64');
        }
        if (Buffer.isBuffer(value)) {
            return value;
        }
        if (Array.isArray(value)) {
            return Buffer.from(value);
        }
        if (value.type === 'Buffer' && Array.isArray(value.data)) {
            return Buffer.from(value.data);
        }
        return value;
    }

    function wrapBinary(value) {
        if (!value) return value;
        if (value._legado_type === 'ByteArray') {
            return value;
        }
        if (Buffer.isBuffer(value)) {
            return {
                _legado_type: 'ByteArray',
                base64: value.toString('base64')
            };
        }
        if (Array.isArray(value)) {
            for (var i = 0; i < value.length; i++) {
                if (typeof value[i] !== 'number') {
                    return value;
                }
            }
            return {
                _legado_type: 'ByteArray',
                base64: Buffer.from(value).toString('base64')
            };
        }
        if (value.type === 'Buffer' && Array.isArray(value.data)) {
            return {
                _legado_type: 'ByteArray',
                base64: Buffer.from(value.data).toString('base64')
            };
        }
        return value;
    }

    function wrapReturnValue(value) {
        if (!value) return value;
        if (value._legado_type === 'StrResponse' || value._legado_type === 'ByteArray') {
            return value;
        }
        return wrapBinary(value);
    }

    function wrapStrResponse(value) {
        if (!value) return value;
        if (value._legado_type === 'StrResponse' && typeof value.body === 'function') {
            return value;
        }
        if (value._legado_type === 'StrResponse') {
            return {
                _legado_type: 'StrResponse',
                url: String(value.url || ""),
                requestUrl: String(value.requestUrl || value.url || ""),
                bodyText: value.bodyText == null ? "" : String(value.bodyText),
                statusCode: Number(value.statusCode || 0),
                messageText: value.messageText == null ? "" : String(value.messageText),
                headersMap: value.headersMap || {},
                body: function() { return createBodyWrapper(this.bodyText); },
                code: function() { return this.statusCode; },
                headers: function() { return createHeadersWrapper(this.headersMap, false); },
                header: function(name) { return this.headers().get(name); },
                message: function() { return this.messageText; },
                raw: function() {
                    var requestUrl = this.requestUrl;
                    return {
                        request: function() {
                            return {
                                url: function() { return requestUrl; }
                            };
                        }
                    };
                },
                toString: function() { return this.bodyText; }
            };
        }
        return value;
    }

    function binaryStringToBuffer(value) {
        var text = String(value == null ? "" : value);
        var arr = [];
        for (var i = 0; i < text.length; i++) {
            arr.push(text.charCodeAt(i) & 0xFF);
        }
        return Buffer.from(arr);
    }

    function toCompatBuffer(value, encodingHint) {
        if (value == null) return Buffer.alloc(0);
        if (Buffer.isBuffer(value)) return value;
        if (value && value._legado_type === 'ByteArray' && value.base64 != null) {
            return Buffer.from(String(value.base64), 'base64');
        }
        if (Array.isArray(value)) {
            return Buffer.from(value.map(function(item) { return Number(item) & 0xFF; }));
        }
        if (value.type === 'Buffer' && Array.isArray(value.data)) {
            return Buffer.from(value.data);
        }
        if (typeof value === 'string') {
            if (encodingHint === 'hex') return Buffer.from(value, 'hex');
            if (encodingHint === 'base64') return Buffer.from(value, 'base64');
            if (encodingHint === 'binary') return binaryStringToBuffer(value);
            return Buffer.from(value, 'utf8');
        }
        return Buffer.from(String(value), 'utf8');
    }

    function bufferToBinaryString(buffer) {
        return Array.prototype.map.call(buffer, function(code) {
            return String.fromCharCode(code);
        }).join('');
    }

    function bufferToWordArray(buffer) {
        var words = [];
        for (var i = 0; i < buffer.length; i++) {
            words[(i / 4) | 0] |= buffer[i] << (24 - 8 * (i % 4));
        }
        return { words: words, sigBytes: buffer.length };
    }

    function wordArrayToBuffer(wordArray) {
        if (!wordArray) return Buffer.alloc(0);
        if (Buffer.isBuffer(wordArray)) return wordArray;
        if (Array.isArray(wordArray)) return Buffer.from(wordArray.map(function(item) { return Number(item) & 0xFF; }));
        var words = wordArray.words || [];
        var sigBytes = Number(wordArray.sigBytes != null ? wordArray.sigBytes : words.length * 4);
        var buffer = Buffer.alloc(Math.max(0, sigBytes));
        for (var i = 0; i < sigBytes; i++) {
            buffer[i] = (words[(i / 4) | 0] >>> (24 - 8 * (i % 4))) & 0xFF;
        }
        return buffer;
    }

    function asCompatResult(buffer, options) {
        var opts = options || {};
        if (opts.asBytes) return Array.from(buffer.values());
        if (opts.asString) return bufferToBinaryString(buffer);
        if (opts.asBase64) return buffer.toString('base64');
        return buffer.toString('hex');
    }

    function createDigestFunction(algo) {
        var fn = function(message, options) {
            var digest = crypto.createHash(algo).update(toCompatBuffer(message)).digest();
            return asCompatResult(digest, options);
        };
        fn._algo = algo;
        return fn;
    }

    function createHmacFunction(hashFn, message, key, options) {
        var algo = (hashFn && hashFn._algo) || 'sha1';
        var digest = crypto
            .createHmac(algo, toCompatBuffer(key))
            .update(toCompatBuffer(message))
            .digest();
        return asCompatResult(digest, options);
    }

    var legacyCrypto = {
        util: {
            randomBytes: function(len) {
                return Array.from(crypto.randomBytes(Math.max(0, Number(len || 0))).values());
            },
            bytesToWords: function(bytes) {
                return bufferToWordArray(toCompatBuffer(bytes)).words;
            },
            wordsToBytes: function(words) {
                return Array.from(wordArrayToBuffer({ words: words || [], sigBytes: (words || []).length * 4 }).values());
            },
            bytesToHex: function(bytes) {
                return toCompatBuffer(bytes).toString('hex');
            },
            hexToBytes: function(hex) {
                return Array.from(toCompatBuffer(hex, 'hex').values());
            },
            bytesToBase64: function(bytes) {
                return toCompatBuffer(bytes).toString('base64');
            },
            base64ToBytes: function(text) {
                return Array.from(toCompatBuffer(text, 'base64').values());
            }
        },
        charenc: {
            UTF8: {
                stringToBytes: function(text) { return Array.from(toCompatBuffer(text).values()); },
                bytesToString: function(bytes) { return toCompatBuffer(bytes).toString('utf8'); }
            },
            Binary: {
                stringToBytes: function(text) { return Array.from(toCompatBuffer(text, 'binary').values()); },
                bytesToString: function(bytes) { return bufferToBinaryString(toCompatBuffer(bytes)); }
            }
        }
    };
    legacyCrypto.MD5 = createDigestFunction('md5');
    legacyCrypto.SHA1 = createDigestFunction('sha1');
    legacyCrypto.SHA256 = createDigestFunction('sha256');
    legacyCrypto.HMAC = createHmacFunction;

    function shellQuote(value) {
        return "'" + String(value == null ? "" : value).replace(/'/g, "'\\''") + "'";
    }

    function parseOptionUrl(url) {
        var urlStr = String(url || "");
        var actualUrl = urlStr;
        var options = {};
        var splitIdx = -1;
        for (var i = urlStr.length - 2; i >= 0; i--) {
            if (urlStr.substring(i, i + 2) === ',{') {
                try {
                    options = JSON.parse(urlStr.substring(i + 1));
                    splitIdx = i;
                    break;
                } catch (e) {}
            }
        }
        if (splitIdx !== -1) {
            actualUrl = urlStr.substring(0, splitIdx);
        }
        return { actualUrl: actualUrl, options: options };
    }

    function parseHeaderBlock(text) {
        var raw = String(text || "").trim();
        if (!raw) {
            return { statusCode: 0, messageText: "", headersMap: {} };
        }
        var blocks = raw.split(/\r?\n\r?\n(?=HTTP\/)/);
        var block = blocks[blocks.length - 1];
        var lines = block.split(/\r?\n/);
        var statusLine = lines.shift() || "";
        var match = statusLine.match(/^HTTP\/\S+\s+(\d+)\s*(.*)$/);
        var headersMap = {};
        for (var i = 0; i < lines.length; i++) {
            var idx = lines[i].indexOf(':');
            if (idx > 0) {
                headersMap[lines[i].substring(0, idx).trim()] = lines[i].substring(idx + 1).trim();
            }
        }
        return {
            statusCode: match ? Number(match[1] || 0) : 0,
            messageText: match ? String(match[2] || "") : "",
            headersMap: headersMap
        };
    }

    function cloneHeaders(headers) {
        var out = {};
        if (!headers) return out;
        for (var key in headers) {
            if (Object.prototype.hasOwnProperty.call(headers, key) && headers[key] != null) {
                out[String(key)] = String(headers[key]);
            }
        }
        return out;
    }

    function headerName(headers, target) {
        if (!headers) return "";
        var lower = String(target || "").toLowerCase();
        for (var key in headers) {
            if (String(key).toLowerCase() === lower) {
                return key;
            }
        }
        return "";
    }

    function getSourceDefaultHeaders() {
        var headers = {};
        try {
            if (ctx.source_data && ctx.source_data.header) {
                headers = cloneHeaders(JSON.parse(ctx.source_data.header) || {});
            }
        } catch (e) {}
        try {
            if (ctx._source_vars && ctx._source_vars._login_header) {
                var loginHeaders = cloneHeaders(JSON.parse(ctx._source_vars._login_header) || {});
                for (var name in loginHeaders) {
                    headers[name] = loginHeaders[name];
                }
            }
        } catch (e) {}
        return headers;
    }

    function requestWithCurl(url, extra) {
        extra = extra || {};
        var parsed = parseOptionUrl(url);
        var actualUrl = parsed.actualUrl;
        var options = parsed.options || {};
        var method = String(extra.method || options.method || 'GET').toUpperCase();
        var headers = getSourceDefaultHeaders();
        if (options.headers) {
            for (var key in options.headers) headers[key] = String(options.headers[key]);
        }
        if (extra.headers) {
            for (var h in extra.headers) headers[h] = String(extra.headers[h]);
        }
        var cookieHeaderKey = headerName(headers, 'Cookie') || headerName(headers, 'cookie');
        if (!cookieHeaderKey) {
            try {
                var implicitCookie = cookie.getCookie(actualUrl);
                if (implicitCookie) {
                    headers['Cookie'] = implicitCookie;
                }
            } catch (e) {}
        }
        var body = extra.body != null ? extra.body : options.body;
        var followRedirects = extra.followRedirects !== false;
        var cookieJar = ctx._cookie_file;
        var id = crypto.randomUUID();
        var headerPath = '/tmp/legado_hdr_' + id + '.txt';
        var bodyPath = '/tmp/legado_body_' + id + '.txt';
        var cmd = 'curl -sS --compressed --connect-timeout 10 --max-time 30 -c ' + shellQuote(cookieJar) + ' -b ' + shellQuote(cookieJar);
        if (followRedirects) {
            cmd += ' -L';
        }
        cmd += ' -X ' + shellQuote(method);
        cmd += ' -D ' + shellQuote(headerPath) + ' -o ' + shellQuote(bodyPath);
        cmd += ' -w ' + shellQuote('\n__EFFECTIVE_URL__:%{url_effective}');
        for (var name in headers) {
            cmd += ' -H ' + shellQuote(name + ': ' + String(headers[name]));
        }
        if (body != null && method !== 'GET' && method !== 'HEAD') {
            var bodyText = typeof body === 'string' ? body : JSON.stringify(body);
            cmd += ' --data ' + shellQuote(bodyText);
        }
        cmd += ' ' + shellQuote(actualUrl);
        try {
            var meta = String(child_process.execSync(cmd));
            var headerText = '';
            var bodyTextOut = '';
            try { headerText = fs.readFileSync(headerPath, 'utf8'); } catch (e) {}
            try { bodyTextOut = fs.readFileSync(bodyPath, 'utf8'); } catch (e) {}
            try { fs.unlinkSync(headerPath); } catch (e) {}
            try { fs.unlinkSync(bodyPath); } catch (e) {}
            var info = parseHeaderBlock(headerText);
            var effectiveMatch = meta.match(/__EFFECTIVE_URL__:(.*)$/m);
            return wrapStrResponse({
                _legado_type: 'StrResponse',
                url: effectiveMatch ? String(effectiveMatch[1] || "").trim() : actualUrl,
                requestUrl: effectiveMatch ? String(effectiveMatch[1] || "").trim() : actualUrl,
                bodyText: method === 'HEAD' ? "" : bodyTextOut,
                statusCode: info.statusCode,
                messageText: info.messageText,
                headersMap: info.headersMap
            });
        } catch (e) {
            try { fs.unlinkSync(headerPath); } catch (err) {}
            try { fs.unlinkSync(bodyPath); } catch (err) {}
            logToFile("HTTP ERROR: " + e);
            return wrapStrResponse({
                _legado_type: 'StrResponse',
                url: actualUrl,
                requestUrl: actualUrl,
                bodyText: String(e),
                statusCode: 599,
                messageText: String(e),
                headersMap: {}
            });
        }
    }

    function resolvePath(path) {
        var value = String(path || "");
        if (value.startsWith('~')) {
            var home = process.env.HOME || '';
            return home ? home + value.substring(1) : value;
        }
        if (value.startsWith('/')) {
            return value;
        }
        return require('path').join(process.cwd(), value);
    }

    function htmlFormatImpl(value, baseUrl) {
        var html = String(value == null ? "" : value);
        if (!html) return "";
        var base = String(baseUrl || "");
        if (base) {
            html = html.replace(/src="([^"]*)"/gi, function(_, src) {
                try { return 'src="' + new URL(src, base).toString() + '"'; } catch (e) { return 'src="' + src + '"'; }
            });
            html = html.replace(/src='([^']*)'/gi, function(_, src) {
                try { return 'src="' + new URL(src, base).toString() + '"'; } catch (e) { return 'src="' + src + '"'; }
            });
        }
        return html;
    }

    function toURLImpl(url, baseUrl) {
        var parsed = baseUrl ? new URL(String(url || ""), String(baseUrl || "")) : new URL(String(url || ""));
        var searchParams = {};
        var hasParams = false;
        parsed.searchParams.forEach(function(value, key) {
            searchParams[key] = value;
            hasParams = true;
        });
        return {
            host: parsed.hostname || "",
            origin: parsed.origin || "",
            pathname: parsed.pathname || "",
            searchParams: hasParams ? searchParams : null
        };
    }

    function analyzeRuleBridge(payload) {
        var raw = child_process.execFileSync(
            'python3',
            ['-m', 'legado_engine.js_analyze_bridge'],
            {
                input: JSON.stringify(payload),
                maxBuffer: 10 * 1024 * 1024
            }
        ).toString();
        var parsed = JSON.parse(raw || '{}');
        return parsed.result;
    }

    var java = {
        ajax: function(url) {
            return requestWithCurl(url, { followRedirects: true }).body().string();
        },
        put: function(k, v) {
            var val = v == null ? "" : String(v);
            ctx._updates[k] = val;
            ctx._vars[k] = val;
            return val;
        },
        get: function(k, headers) {
            if (arguments.length > 1) {
                return requestWithCurl(k, { method: 'GET', headers: headers || {}, followRedirects: false });
            }
            var val = ctx._vars[k];
            return val == null ? "" : String(val);
        },
        log: function(msg) {
            logToFile("JS LOG: " + msg);
            ctx._events.logs.push(String(msg));
            return msg;
        },
        logType: function(any) {
            if (any == null) {
                java.log("null");
                return;
            }
            if (any && any._legado_type) {
                java.log(any._legado_type);
                return;
            }
            if (Buffer.isBuffer(any)) {
                java.log("Buffer");
                return;
            }
            if (Array.isArray(any)) {
                java.log("Array");
                return;
            }
            var ctor = any && any.constructor && any.constructor.name;
            java.log(ctor || typeof any);
        },
        
        // Crypto / Encoding
        base64Encode: function(str) { return Buffer.from(str).toString('base64'); },
        base64Decode: function(str) { return Buffer.from(str, 'base64').toString('utf8'); },
        base64DecodeToByteArray: function(str) {
            try {
                return Buffer.from(String(str || ""), 'base64');
            } catch (e) {
                return Buffer.alloc(0);
            }
        },
        strToBytes: function(str, charset) {
            return Buffer.from(String(str == null ? "" : str), charset || 'utf8');
        },
        bytesToStr: function(bytes, charset) {
            try {
                return unwrapBinary(bytes).toString(charset || 'utf8');
            } catch (e) {
                return "";
            }
        },
        hexDecodeToByteArray: function(hex) {
            try {
                return Buffer.from(String(hex || ""), 'hex');
            } catch (e) {
                return Buffer.alloc(0);
            }
        },
        hexDecodeToString: function(str) { 
            try {
                if (!str) return "";
                // If starts with { or [ it's likely JSON, not hex
                if (str.trim().startsWith('{') || str.trim().startsWith('[')) return str;
                
                var buf = Buffer.from(str, 'hex');
                if (buf.length > 0) return buf.toString('utf8');
                return str;
            } catch(e) { return str; }
        },
        hexEncodeToString: function(str) {
            return Buffer.from(String(str == null ? "" : str), 'utf8').toString('hex');
        },
        md5: function(str) { return crypto.createHash('md5').update(str).digest('hex'); },
        md5Encode: function(str) { return crypto.createHash('md5').update(str).digest('hex'); },
        md5Encode16: function(str) {
            var digest = crypto.createHash('md5').update(str).digest('hex');
            return digest.substring(8, 24);
        },
        sha1: function(str) { return crypto.createHash('sha1').update(str).digest('hex'); },
        sha256: function(str) { return crypto.createHash('sha256').update(str).digest('hex'); },
        encodeURI: function(str) { return encodeURIComponent(String(str == null ? "" : str)); },
        randomUUID: function() {
            return crypto.randomUUID();
        },
        htmlFormat: function(str) {
            return htmlFormatImpl(str, ctx.baseUrl || "");
        },
        toURL: function(url, baseUrl) {
            return toURLImpl(url, baseUrl || ctx.baseUrl || "");
        },
        setContent: function(content, baseUrl) {
            var nextBase = baseUrl == null ? (ctx._analysis_base_url || ctx.baseUrl || "") : String(baseUrl);
            var result = analyzeRuleBridge({
                operation: 'set_content',
                content: ctx._analysis_content,
                baseUrl: ctx._analysis_base_url || ctx.baseUrl || "",
                redirectUrl: ctx._analysis_redirect_url || ctx.baseUrl || "",
                source: ctx.source_data || {},
                book: ctx.book || {},
                chapter: ctx.chapter || {},
                newContent: content,
                newBaseUrl: nextBase
            });
            ctx._analysis_content = result.content;
            ctx._analysis_base_url = result.baseUrl || nextBase;
            ctx._analysis_redirect_url = result.baseUrl || nextBase;
        },
        getString: function(ruleStr, mContent, isUrl) {
            return analyzeRuleBridge({
                operation: 'get_string',
                rule: ruleStr,
                mContent: mContent,
                isUrl: !!isUrl,
                content: ctx._analysis_content,
                baseUrl: ctx._analysis_base_url || ctx.baseUrl || "",
                redirectUrl: ctx._analysis_redirect_url || ctx.baseUrl || "",
                source: ctx.source_data || {},
                book: ctx.book || {},
                chapter: ctx.chapter || {}
            });
        },
        getStringList: function(ruleStr, mContent, isUrl) {
            return analyzeRuleBridge({
                operation: 'get_string_list',
                rule: ruleStr,
                mContent: mContent,
                isUrl: !!isUrl,
                content: ctx._analysis_content,
                baseUrl: ctx._analysis_base_url || ctx.baseUrl || "",
                redirectUrl: ctx._analysis_redirect_url || ctx.baseUrl || "",
                source: ctx.source_data || {},
                book: ctx.book || {},
                chapter: ctx.chapter || {}
            }) || [];
        },
        getElement: function(ruleStr) {
            return analyzeRuleBridge({
                operation: 'get_element',
                rule: ruleStr,
                content: ctx._analysis_content,
                baseUrl: ctx._analysis_base_url || ctx.baseUrl || "",
                redirectUrl: ctx._analysis_redirect_url || ctx.baseUrl || "",
                source: ctx.source_data || {},
                book: ctx.book || {},
                chapter: ctx.chapter || {}
            });
        },
        getElements: function(ruleStr) {
            return analyzeRuleBridge({
                operation: 'get_elements',
                rule: ruleStr,
                content: ctx._analysis_content,
                baseUrl: ctx._analysis_base_url || ctx.baseUrl || "",
                redirectUrl: ctx._analysis_redirect_url || ctx.baseUrl || "",
                source: ctx.source_data || {},
                book: ctx.book || {},
                chapter: ctx.chapter || {}
            }) || [];
        },
        cacheFile: function(url, saveTime) {
            var cacheKey = java.md5Encode16(String(url || ""));
            var now = Date.now() / 1000.0;
            var entry = ctx._text_cache[cacheKey];
            if (entry && (!entry.expires_at || Number(entry.expires_at) <= 0 || Number(entry.expires_at) > now)) {
                return String(entry.value || "");
            }
            var text = requestWithCurl(url, { followRedirects: true }).body().string();
            var saveSeconds = Number(saveTime || 0);
            ctx._text_cache[cacheKey] = {
                value: String(text || ""),
                expires_at: saveSeconds > 0 ? now + saveSeconds : 0
            };
            return text;
        },
        importScript: function(path) {
            var value = String(path || "");
            if (value.startsWith('http://') || value.startsWith('https://')) {
                return java.cacheFile(value, 0);
            }
            return fs.readFileSync(resolvePath(value), 'utf8');
        },

        // Utils
        strToJson: function(str) { try { return JSON.parse(str); } catch(e) { return null; } },
        jsonToStr: function(obj) { return JSON.stringify(obj); },
        htmlEscape: function(str) { 
             return str.replace(/&/g, '&amp;')
                       .replace(/</g, '&lt;')
                       .replace(/>/g, '&gt;')
                       .replace(/"/g, '&quot;')
                       .replace(/'/g, '&#039;');
        },
        htmlUnescape: function(str) {
             return str.replace(/&amp;/g, '&')
                       .replace(/&lt;/g, '<')
                       .replace(/&gt;/g, '>')
                       .replace(/&quot;/g, '"')
                       .replace(/&#039;/g, "'");
        },

        // Legado specific
        longToast: function(msg) {
            logToFile("TOAST: " + msg);
            ctx._events.toasts.push(String(msg));
        },
        toast: function(msg) {
            logToFile("TOAST: " + msg);
            ctx._events.toasts.push(String(msg));
        },
        connect: function(url, header) {
            var headerObj = {};
            if (header) {
                try {
                    headerObj = typeof header === 'string' ? JSON.parse(header) : header;
                } catch (e) {
                    headerObj = {};
                }
            }
            return requestWithCurl(url, { headers: headerObj, followRedirects: true });
        },
        post: function(url, body, headers) {
            return requestWithCurl(url, { method: 'POST', body: body, headers: headers || {}, followRedirects: false });
        },
        head: function(url, headers) {
            return requestWithCurl(url, { method: 'HEAD', headers: headers || {}, followRedirects: false });
        },
        getHeaderMap: function() {
            return createHeadersWrapper(ctx._header_map, true);
        },
        getResponse: function() {
            return requestWithCurl(ctx.url || "", { headers: ctx._header_map || {}, followRedirects: true });
        },
        webView: function(html, url, js) {
            throw new Error('Unsupported headless operation: webView');
        },
        webViewGetSource: function(html, url, js, sourceRegex) {
            throw new Error('Unsupported headless operation: webViewGetSource');
        },
        webViewGetOverrideUrl: function(html, url, js, overrideUrlRegex) {
            throw new Error('Unsupported headless operation: webViewGetOverrideUrl');
        },
        startBrowserAwait: function(url, title) {
            if (!ctx._allow_browser_capture) {
                throw new Error('Unsupported headless operation: startBrowserAwait');
            }
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
            return { body: function() { return ""; } };
        },
        startBrowser: function(url, title) {
            if (!ctx._allow_browser_capture) {
                throw new Error('Unsupported headless operation: startBrowser');
            }
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        getVerificationCode: function(url) {
            throw new Error('Unsupported headless operation: getVerificationCode');
        },
        deviceID: function() { return String(ctx._device_id || ""); },
        androidId: function() { return String(ctx._android_id || ctx._device_id || ""); },
        getCookie: function(url) { return ""; },
        timeFormat: function(timeMs) {
            try {
                var value = Number(timeMs);
                if (value > 10000000000) value = value / 1000;
                var d = new Date(value * 1000);
                var pad = function(n) { return String(n).padStart(2, '0'); };
                return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
                    pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
            } catch (e) { return ""; }
        },
        timeFormatUTC: function(timeMs, format, sh) {
            try {
                var value = Number(timeMs);
                if (value > 10000000000) value = value / 1000;
                var d = new Date((value + Number(sh || 0) * 3600) * 1000);
                var pad = function(n) { return String(n).padStart(2, '0'); };
                return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) + ' ' +
                    pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ':' + pad(d.getUTCSeconds());
            } catch (e) { return ""; }
        },
        getWebViewUA: function() {
            return "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36";
        },
        startBrowserDp: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        showReadingBrowser: function(url, title) {
            ctx._events.browserUrl = String(url || "");
            ctx._events.browserTitle = String(title || "");
        },
        // Chinese simplified↔traditional conversion (stub — full conversion needs opencc)
        t2s: function(text) {
            // Mirror JsExtensions.t2s(): traditional → simplified
            // Real conversion requires opencc; return as-is for now but delegate via bridge if available
            try {
                var r = analyzeRuleBridge({operation: 't2s', text: String(text || "")});
                return (r && r.result != null) ? String(r.result) : String(text || "");
            } catch(e) { return String(text || ""); }
        },
        s2t: function(text) {
            // Mirror JsExtensions.s2t(): simplified → traditional
            try {
                var r = analyzeRuleBridge({operation: 's2t', text: String(text || "")});
                return (r && r.result != null) ? String(r.result) : String(text || "");
            } catch(e) { return String(text || ""); }
        },
        // toNumChapter: convert Chinese numeral chapter title to numeric form
        toNumChapter: function(s) {
            if (s == null) return null;
            try {
                var r = analyzeRuleBridge({operation: 'toNumChapter', text: String(s)});
                return (r && r.result != null) ? String(r.result) : String(s);
            } catch(e) { return String(s); }
        },
        // ajaxAll: fetch multiple URLs concurrently, returns array of StrResponse
        ajaxAll: function(urlList) {
            try {
                if (!Array.isArray(urlList)) return [];
                return urlList.map(function(url) { return java.ajax(url); });
            } catch(e) { return []; }
        },
        // getZipStringContent: fetch a zip from URL and extract a named file from it
        getZipStringContent: function(url, path, charsetName) {
            try {
                var r = analyzeRuleBridge({
                    operation: 'getZipStringContent',
                    url: String(url || ""),
                    path: String(path || ""),
                    charsetName: charsetName ? String(charsetName) : null
                });
                return (r != null) ? String(r) : "";
            } catch(e) { return ""; }
        },
        qread: function() { return false; }
    };
    
    // Global Helper: getArguments
    var getArguments = function(jsonStr, key) {
        try {
            if (!jsonStr) return "";
            var obj = JSON.parse(jsonStr);
            return obj[key] || "";
        } catch(e) { return ""; }
    };

    var cookie = {
        getCookie: function(url) {
            try {
                var cookiesMap = {};
                var domain = new URL(url).hostname;
                
                // 1. From Python ctx._cookies
                for (var d in ctx._cookies) {
                    if (domain.endsWith(d)) {
                         var parts = ctx._cookies[d].split(';');
                         for (var i = 0; i < parts.length; i++) {
                             var p = parts[i].trim().split('=');
                             if (p.length >= 2) cookiesMap[p[0]] = p.slice(1).join('=');
                         }
                    }
                }
                
                // 2. From file
                try {
                    var content = fs.readFileSync(ctx._cookie_file, 'utf8');
                    var lines = content.split('\n');
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i].trim();
                        if (!line || line.startsWith('#')) continue;
                        var parts = line.split('\t');
                        if (parts.length >= 7) {
                            var d = parts[0];
                            // domain match logic
                            if (d === domain || domain.endsWith(d) || (d.startsWith('.') && domain.endsWith(d.substring(1)))) {
                                 cookiesMap[parts[5]] = parts[6];
                            }
                        }
                    }
                } catch(e) {}
                
                var res = [];
                for (var k in cookiesMap) {
                    res.push(k + '=' + cookiesMap[k]);
                }
                return res.join('; ');
            } catch (e) { return ""; }
        },
        removeCookie: function(url) {
             try {
                var content = "";
                try { content = fs.readFileSync(ctx._cookie_file, 'utf8'); } catch(e) {}
                var domain = new URL(url).hostname;
                var lines = content.split('\n');
                var newLines = [];
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim();
                    if (!line || line.startsWith('#')) {
                        newLines.push(lines[i]);
                        continue;
                    }
                    var parts = line.split('\t');
                    if (parts.length >= 7) {
                        var d = parts[0];
                        if (d === domain || d === '.'+domain || domain.endsWith(d)) {
                            continue;
                        }
                    }
                    newLines.push(lines[i]);
                }
                fs.writeFileSync(ctx._cookie_file, newLines.join('\n'));
                if (ctx._cookies) {
                    delete ctx._cookies[domain];
                    delete ctx._cookies['.' + domain];
                }
            } catch(e) {}
        },
        setCookie: function(url, c) {
            try {
                 var domain = new URL(url).hostname;
                 var jarMap = {};
                 try {
                     var existingContent = fs.readFileSync(ctx._cookie_file, 'utf8');
                     var existingLines = existingContent.split('\n');
                     for (var i = 0; i < existingLines.length; i++) {
                         var line = existingLines[i].trim();
                         if (!line || line.startsWith('#')) continue;
                         var cols = line.split('\t');
                         if (cols.length >= 7) {
                             var jarDomain = cols[0];
                             if (jarDomain === domain || jarDomain === '.' + domain || domain.endsWith(jarDomain)) {
                                 jarMap[cols[5]] = cols[6];
                             }
                         }
                     }
                 } catch (e) {}
                 var parts = String(c == null ? "" : c).split(';');
                 for (var j = 0; j < parts.length; j++) {
                     var part = parts[j].trim();
                     if (!part) continue;
                     var idx = part.indexOf('=');
                     if (idx <= 0) continue;
                     var name = part.substring(0, idx).trim();
                     var value = part.substring(idx + 1).trim();
                     if (!name) continue;
                     jarMap[name] = value;
                 }
                 var now = Math.floor(Date.now() / 1000);
                 var exp = now + 31536000;
                 var lines = [];
                 for (var key in jarMap) {
                     lines.push(`${domain}\tTRUE\t/\tFALSE\t${exp}\t${key}\t${jarMap[key]}`);
                 }
                 var contentOut = lines.join('\n');
                 if (contentOut) {
                     contentOut += '\n';
                 }
                 var preserve = [];
                 try {
                     var priorContent = fs.readFileSync(ctx._cookie_file, 'utf8');
                     var priorLines = priorContent.split('\n');
                     for (var k = 0; k < priorLines.length; k++) {
                         var priorLine = priorLines[k].trim();
                         if (!priorLine || priorLine.startsWith('#')) {
                             if (priorLines[k]) preserve.push(priorLines[k]);
                             continue;
                         }
                         var priorCols = priorLine.split('\t');
                         if (priorCols.length >= 7) {
                             var priorDomain = priorCols[0];
                             if (priorDomain === domain || priorDomain === '.' + domain || domain.endsWith(priorDomain)) {
                                 continue;
                             }
                         }
                         preserve.push(priorLines[k]);
                     }
                 } catch (e) {}
                 if (preserve.length) {
                     contentOut = preserve.join('\n') + '\n' + contentOut;
                 }
                 fs.writeFileSync(ctx._cookie_file, contentOut);
                 if (ctx._cookies) {
                     var merged = [];
                     for (var cookieName in jarMap) {
                         merged.push(cookieName + '=' + jarMap[cookieName]);
                     }
                     ctx._cookies[domain] = merged.join('; ');
                 }
            } catch(e) {}
        },
        getKey: function(url, key) {
            try {
                var cookieStr = cookie.getCookie(url);
                if (!cookieStr) return null;
                var parts = cookieStr.split(';');
                for (var i = 0; i < parts.length; i++) {
                    var p = parts[i].trim();
                    var idx = p.indexOf('=');
                    if (idx !== -1 && p.substring(0, idx).trim() === key) {
                        return p.substring(idx + 1).trim();
                    }
                }
            } catch(e) {}
            return null;
        }
    };

    var source = {
        getVariable: function() { return ctx._source_vars && ctx._source_vars.custom_variable_blob ? ctx._source_vars.custom_variable_blob : ""; },
        setVariable: function(v) { ctx._updates['source_var'] = v; },
        loginVariable: function() { return ""; },
        getLoginInfo: function() { return ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}"; },
        getLoginInfoMap: function() {
            var info = ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}";
            try { return createHeadersWrapper(JSON.parse(info) || {}, true); } catch(e) { return createHeadersWrapper({}, true); }
        },
        putLoginInfo: function(info) { ctx._updates['login_info'] = info; },
        getLoginHeader: function() { return ctx._source_vars && ctx._source_vars._login_header ? ctx._source_vars._login_header : ""; },
        putLoginHeader: function(header) {
            var value = header == null ? "" : String(header);
            ctx._updates['login_header'] = value;
            ctx._source_vars._login_header = value;
        },
        removeLoginHeader: function() {
            ctx._updates['login_header'] = "";
            ctx._source_vars._login_header = "";
        },
        getHeaderMap: function(hasLoginHeader) {
            var headers = {};
            try {
                if (ctx.source_data && ctx.source_data.header) {
                    headers = JSON.parse(ctx.source_data.header) || {};
                }
            } catch (e) {}
            if (hasLoginHeader) {
                try {
                    var loginHeader = source.getLoginHeader();
                    if (loginHeader) {
                        var loginMap = JSON.parse(loginHeader) || {};
                        for (var name in loginMap) {
                            headers[name] = loginMap[name];
                        }
                    }
                } catch (e) {}
            }
            return createHeadersWrapper(headers, true);
        },
        getKey: function() { return ctx.source_data ? (ctx.source_data.bookSourceUrl || ctx.source_data.sourceUrl || "") : ""; },
        put: function(k, v) {
            var key = String(k);
            var val = v == null ? "" : String(v);
            ctx._source_updates[key] = val;
            ctx._source_cache[key] = val;
            return val;
        },
        get: function(k) {
            var val = ctx._source_cache[String(k)];
            return val == null ? "" : String(val);
        }
    };
    if (ctx.source_data) {
        Object.assign(source, ctx.source_data);
        // Restore methods overwritten by Object.assign
        source.getVariable = function() { return ctx._source_vars && ctx._source_vars.custom_variable_blob ? ctx._source_vars.custom_variable_blob : ""; };
        source.setVariable = function(v) { ctx._updates['source_var'] = v; };
        source.getLoginInfo = function() { return ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}"; };
        source.getLoginInfoMap = function() {
            var info = ctx._source_vars && ctx._source_vars._login_info ? ctx._source_vars._login_info : "{}";
            try { return createHeadersWrapper(JSON.parse(info) || {}, true); } catch(e) { return createHeadersWrapper({}, true); }
        };
        source.putLoginInfo = function(info) { ctx._updates['login_info'] = info; };
        source.getLoginHeader = function() { return ctx._source_vars && ctx._source_vars._login_header ? ctx._source_vars._login_header : ""; };
        source.putLoginHeader = function(header) {
            var value = header == null ? "" : String(header);
            ctx._updates['login_header'] = value;
            ctx._source_vars._login_header = value;
        };
        source.removeLoginHeader = function() {
            ctx._updates['login_header'] = "";
            ctx._source_vars._login_header = "";
        };
        source.getHeaderMap = function(hasLoginHeader) {
            var headers = {};
            try {
                if (ctx.source_data && ctx.source_data.header) {
                    headers = JSON.parse(ctx.source_data.header) || {};
                }
            } catch (e) {}
            if (hasLoginHeader) {
                try {
                    var loginHeader = source.getLoginHeader();
                    if (loginHeader) {
                        var loginMap = JSON.parse(loginHeader) || {};
                        for (var name in loginMap) {
                            headers[name] = loginMap[name];
                        }
                    }
                } catch (e) {}
            }
            return createHeadersWrapper(headers, true);
        };
        source.getKey = function() { return ctx.source_data ? (ctx.source_data.bookSourceUrl || ctx.source_data.sourceUrl || "") : ""; };
        source.loginVariable = function() { return ""; };
        source.put = function(k, v) {
            var key = String(k);
            var val = v == null ? "" : String(v);
            ctx._source_updates[key] = val;
            ctx._source_cache[key] = val;
            return val;
        };
        source.get = function(k) {
            var val = ctx._source_cache[String(k)];
            return val == null ? "" : String(val);
        };
    }

    // ------------------------------------------------------------------
    // Context Injection
    // ------------------------------------------------------------------
    
    var baseUrl = ctx.baseUrl;
    var url = ctx.url;
    var result = ctx.result && ctx.result._legado_type === 'StrResponse' ? wrapStrResponse(ctx.result) : unwrapBinary(ctx.result);
    var cache = {
        put: function(k, v) {
            var key = String(k);
            ctx._cache[key] = v;
            ctx._cache_updates[key] = v;
            return v;
        },
        get: function(k, defaultValue) {
            var key = String(k);
            if (Object.prototype.hasOwnProperty.call(ctx._cache, key)) return ctx._cache[key];
            return defaultValue == null ? "" : defaultValue;
        },
        remove: function(k) {
            var key = String(k);
            delete ctx._cache[key];
            ctx._cache_updates[key] = null;
        },
        contains: function(k) {
            return Object.prototype.hasOwnProperty.call(ctx._cache, String(k));
        },
        clear: function() {
            ctx._cache = {};
            ctx._cache_cleared = true;
            ctx._cache_updates = {};
        }
    };
    var book = ctx.book;
    if (book) {
        book.getVariable = function(key) {
             try {
                 if (!this.variable) return null;
                 var obj = JSON.parse(this.variable);
                 return obj[key];
             } catch(e) { return null; }
        };
        book.getVariableMap = function() {
             try {
                 return createHeadersWrapper(JSON.parse(this.variable || "{}") || {}, true);
             } catch (e) {
                 return createHeadersWrapper({}, true);
             }
        };
        book.getName = function() { return this.name || ""; };
        book.getCoverUrl = function() { return this.coverUrl || ""; };
        book.getTotalChapterNum = function() { return Number(this.totalChapterNum || 0); };
        book.setUseReplaceRule = function(val) {
             ctx._updates['book_use_replace_rule'] = !!val;
        };
    }
    var page = ctx.page;
    var key = ctx.key;
    var chapter = ctx.chapter;
    if (chapter) {
        chapter.getIndex = function() { return Number(this.index || 0); };
    }
    var title = ctx.title;
    var nextChapterUrl = ctx.nextChapterUrl;
    var rssArticle = ctx.rssArticle;

    var root = (typeof globalThis !== 'undefined') ? globalThis : this;
    root.java = java;
    root.cookie = cookie;
    root.source = source;
    root.baseUrl = baseUrl;
    root.url = url;
    root.result = result;
    root.book = book;
    root.page = page;
    root.key = key;
    root.chapter = chapter;
    root.title = title;
    root.nextChapterUrl = nextChapterUrl;
    root.rssArticle = rssArticle;
    root.cache = cache;
    root.LegacyCrypto = legacyCrypto;
    root.Crypto = legacyCrypto;
    root.CryptoJS = root.CryptoJS || {
        enc: {
            Utf8: {
                parse: function(text) { return bufferToWordArray(toCompatBuffer(text)); },
                stringify: function(wordArray) { return wordArrayToBuffer(wordArray).toString('utf8'); }
            },
            Hex: {
                parse: function(text) { return bufferToWordArray(toCompatBuffer(text, 'hex')); },
                stringify: function(wordArray) { return wordArrayToBuffer(wordArray).toString('hex'); }
            },
            Base64: {
                parse: function(text) { return bufferToWordArray(toCompatBuffer(text, 'base64')); },
                stringify: function(wordArray) { return wordArrayToBuffer(wordArray).toString('base64'); }
            }
        },
        MD5: function(message) { return bufferToWordArray(toCompatBuffer(legacyCrypto.MD5(message, { asBytes: true }))); },
        SHA1: function(message) { return bufferToWordArray(toCompatBuffer(legacyCrypto.SHA1(message, { asBytes: true }))); },
        SHA256: function(message) { return bufferToWordArray(toCompatBuffer(legacyCrypto.SHA256(message, { asBytes: true }))); },
        HmacSHA1: function(message, key) {
            return bufferToWordArray(toCompatBuffer(legacyCrypto.HMAC(legacyCrypto.SHA1, message, key, { asBytes: true })));
        },
        HmacSHA256: function(message, key) {
            return bufferToWordArray(toCompatBuffer(legacyCrypto.HMAC(legacyCrypto.SHA256, message, key, { asBytes: true })));
        }
    };
    root.Packages = root.Packages || {};
    // ... other bindings injected by python loop ...
    
    // Inject extra bindings from ctx.extra
    if (ctx.extra) {
        for (var k in ctx.extra) {
            if (k !== 'java' && k !== 'cookie' && k !== 'source') {
                 // Use eval to set local var? No, just assign to this scope?
                 // In strict mode (which function might be), we can't.
                 // We rely on user code accessing them via 'ctx.extra'? No.
                 // We must declare them.
                 // Handled by Python prepending var decls.
            }
        }
    }

    // ------------------------------------------------------------------
    // Execution
    // ------------------------------------------------------------------
    
    // We expect 'code' to be passed in ctx.code
    // Python handles prepending declarations.
    try {
        var r = eval(ctx.code);
        return {
            result: wrapReturnValue(r),
            updates: ctx._updates,
            source_updates: ctx._source_updates,
            events: ctx._events,
            cache_updates: ctx._cache_updates,
            cache_cleared: !!ctx._cache_cleared,
            header_map: ctx._header_map,
            text_cache: ctx._text_cache
        };
    } catch(e) {
        throw e;
    }
}
"""


def _to_json_safe(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, (bytes, bytearray)):
        return {
            "_legado_type": "ByteArray",
            "base64": base64.b64encode(bytes(obj)).decode("ascii"),
        }
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    return obj


def _run_execjs(js_str: str, ctx: Dict[str, Any]) -> Any:
    # Import runtime state from eval module at call time to avoid circular-import
    # issues at module load while still reading the live values.
    from . import eval as _eval_mod
    _JS_RUNTIME = _eval_mod._JS_RUNTIME
    _EXECJS_CONTEXT = _eval_mod._EXECJS_CONTEXT

    if _JS_RUNTIME is None:
        return ctx.get("result")

    # Prepare context for serialization
    source_data = {}
    source_vars = {}
    src = ctx.get("source")
    if src:
        cached_source_data = getattr(src, "_execjs_source_data_cache", None)
        if isinstance(cached_source_data, dict):
            source_data = cached_source_data
        elif hasattr(src, "to_dict"):
            source_data = src.to_dict()
            try:
                setattr(src, "_execjs_source_data_cache", source_data)
            except Exception:
                pass
        if hasattr(src, "_variables"):
             source_vars = src._variables

    engine = resolve_engine(ctx.get("engine"))
    _cookies = {}
    try:
        _cookies = engine.cookie_store._store
    except Exception:
        pass

    vars_map = {}
    if src and hasattr(src, "_variables"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in src._variables.items()})
    book_obj = ctx.get("book")
    if book_obj and hasattr(book_obj, "get_variable_map"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in book_obj.get_variable_map().items()})
    chapter_obj = ctx.get("chapter")
    if chapter_obj and hasattr(chapter_obj, "get_variable_map"):
        vars_map.update({str(k): "" if v is None else str(v) for k, v in chapter_obj.get_variable_map().items()})

    # Build the run context
    run_ctx = {
        "baseUrl": ctx.get("baseUrl"),
        "url": ctx.get("url"),
        "result": _to_json_safe(ctx.get("result")),
        "book": _to_json_safe(ctx.get("book")),
        "chapter": _to_json_safe(ctx.get("chapter")),
        "title": ctx.get("title"),
        "nextChapterUrl": ctx.get("nextChapterUrl"),
        "rssArticle": _to_json_safe(ctx.get("rssArticle")),
        "page": ctx.get("page"),
        "key": ctx.get("key"),
        "source_data": source_data,
        "_source_vars": source_vars,
        "_source_cache": dict(vars_map),
        "_cookies": _cookies,
        "_vars": dict(vars_map),
        "_cache": engine.cache.export(),
        "_cache_updates": {},
        "_cache_cleared": False,
        "_text_cache": engine.export_text_cache(),
        "_analysis_content": ctx.get("src", ctx.get("result")),
        "_analysis_base_url": ctx.get("baseUrl"),
        "_analysis_redirect_url": ctx.get("baseUrl"),
        "_header_map": {
            str(k): str(v)
            for k, v in ((getattr(ctx.get("java"), "getHeaderMap", lambda: {})() or {}).items())
        },
        "_cookie_file": engine.cookie_jar_path,
        "_device_id": str(getattr(engine, "device_id", "")),
        "_android_id": str(getattr(engine, "android_id", getattr(engine, "device_id", ""))),
        "_allow_browser_capture": bool(getattr(ctx.get("java"), "_allow_browser_capture", False)),
        "_updates": {},
        "_source_updates": {},
        "_events": {
            "logs": [],
            "toasts": [],
            "browserUrl": "",
            "browserTitle": "",
        },
        "extra": {},
        "code": ""  # Will be populated
    }

    # Filter other bindings
    for k, v in ctx.items():
        if k not in run_ctx and k not in ("java", "cookie", "source"):
             try:
                 json.dumps(v)
                 run_ctx["extra"][k] = v
             except:
                 pass

    # Prepare user code with var declarations.
    # js_str already contains jsLib (prepended in eval_js), so don't add it again.
    # Skip injecting var declarations for variables already declared with let/const in
    # the user code — re-declaring them with var causes SyntaxError in strict contexts.
    _let_const_decls = set(re.findall(r'\b(?:let|const)\s+(\w+)\b', js_str))
    var_decls = [
        f"var {k} = ctx.extra.{k};"
        for k in run_ctx["extra"]
        if k not in _let_const_decls
    ]

    run_ctx["code"] = "\n".join(var_decls) + "\n" + js_str

    try:
        compiled = getattr(_EXECJS_CONTEXT, "compiled_wrapper", None)
        if compiled is None:
            compiled = _JS_RUNTIME.compile(_EXECJS_WRAPPER)
            _EXECJS_CONTEXT.compiled_wrapper = compiled
        # Call run
        raw_res = compiled.call("run", run_ctx)

        # Sync cookies back to store
        try:
             engine.cookie_store.load_from_file(engine.cookie_jar_path)
        except Exception:
             pass

        if isinstance(raw_res, dict) and "updates" in raw_res:
            updates = raw_res["updates"] or {}
            source_updates = raw_res.get("source_updates") or {}
            events = raw_res.get("events") or {}
            cache_updates = raw_res.get("cache_updates") or {}
            if raw_res.get("cache_cleared"):
                engine.cache.clear()
            for key, value in cache_updates.items():
                if value is None:
                    engine.cache.remove(key)
                else:
                    engine.cache.put(key, value)
            if isinstance(raw_res.get("text_cache"), dict):
                engine.replace_text_cache(raw_res.get("text_cache") or {})
            src = ctx.get("source")
            if src:
                if "source_var" in updates:
                    src.setVariable(updates["source_var"])
                if "login_info" in updates:
                    src.putLoginInfo(updates["login_info"])
                if "login_header" in updates:
                    if updates["login_header"]:
                        src.putLoginHeader(updates["login_header"])
                    else:
                        src.removeLoginHeader()
                for k, v in source_updates.items():
                    src.put(k, v)
            java = ctx.get("java")
            if java:
                if isinstance(raw_res.get("header_map"), dict):
                    header_map = getattr(java, "getHeaderMap", lambda: None)()
                    if isinstance(header_map, dict):
                        header_map.clear()
                        header_map.update(
                            {str(k): str(v) for k, v in (raw_res.get("header_map") or {}).items()}
                        )
                for k, v in updates.items():
                    if k not in ("source_var", "login_info"):
                        java.put(k, v)
                book_obj = ctx.get("book")
                if book_obj is not None and "book_use_replace_rule" in updates and hasattr(book_obj, "set_use_replace_rule"):
                    book_obj.set_use_replace_rule(bool(updates["book_use_replace_rule"]))
                if hasattr(java, "logs") and isinstance(events.get("logs"), list):
                    java.logs.extend(str(item) for item in events.get("logs") or [])
                if hasattr(java, "toasts") and isinstance(events.get("toasts"), list):
                    java.toasts.extend(str(item) for item in events.get("toasts") or [])
                if hasattr(java, "browser_url") and events.get("browserUrl"):
                    java.browser_url = str(events.get("browserUrl") or "")
                if hasattr(java, "browser_title") and events.get("browserTitle") is not None:
                    java.browser_title = str(events.get("browserTitle") or "")
            return raw_res.get("result")
        return raw_res
    except Exception as e:
        detail = str(e)
        if "Unsupported headless operation:" in detail:
            operation = detail.split("Unsupported headless operation:", 1)[1].strip()
            raise UnsupportedHeadlessOperation(operation)
        raise
