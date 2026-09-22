#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import lzma
import os
import re
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
READY_PATH = DATA / "SEAFOOD_QUICK_READY_STATE.json"
API_TOKEN = os.environ.get("SROS_API_TOKEN", "")
PORT = int(os.environ.get("PORT", "8080"))


def normalize_name(value: str) -> str:
    s = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    s = re.sub(r"[^0-9A-Z\u3400-\u9FFF]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return {"BONITO": "BONITA"}.get(s, s)


def is_numeric_query(q: str) -> bool:
    return bool(re.fullmatch(r"\d+", str(q or "").strip()))


def read_b64_xz_parts(folder: Path) -> bytes:
    parts = sorted(folder.glob("part-*.b64"))
    if not parts:
        raise RuntimeError(f"missing data parts: {folder}")
    encoded = "".join(p.read_text(encoding="ascii").strip() for p in parts)
    return lzma.decompress(base64.b64decode(encoded))


def parse_numeric(raw: bytes):
    out = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t", 3)
        if len(p) < 4:
            continue
        key, key_type, profile_id, quickcheck = p
        out.setdefault(key, []).append({
            "key_type": key_type,
            "profile_id": profile_id,
            "quickcheck": quickcheck,
        })
    return out


def parse_alias(raw: bytes):
    out = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        p = line.split("\t", 5)
        if len(p) < 5:
            continue
        alias, alias_type, profile_id, collision_rank, quickcheck = p[:5]
        related = p[5] if len(p) > 5 else ""
        out.setdefault(alias, []).append({
            "alias_type": alias_type,
            "profile_id": profile_id,
            "collision_rank": collision_rank,
            "quickcheck": quickcheck,
            "related": related,
        })
    return out


def load_state():
    ready = json.loads(READY_PATH.read_text(encoding="utf-8"))
    if ready.get("status") != "READY" or ready.get("quick_check_ready") is not True:
        raise RuntimeError("READY_NOT_CURRENT")

    num_raw = read_b64_xz_parts(DATA / "numeric")
    alias_raw = read_b64_xz_parts(DATA / "alias")

    expected_num = ready.get("artifacts", {}).get("numeric_index_sha256")
    expected_alias = ready.get("artifacts", {}).get("alias_index_sha256")
    actual_num = hashlib.sha256(num_raw).hexdigest()
    actual_alias = hashlib.sha256(alias_raw).hexdigest()
    if expected_num and not hmac.compare_digest(expected_num, actual_num):
        raise RuntimeError("NUMERIC_INDEX_SHA_MISMATCH")
    if expected_alias and not hmac.compare_digest(expected_alias, actual_alias):
        raise RuntimeError("ALIAS_INDEX_SHA_MISMATCH")

    numeric = parse_numeric(num_raw)
    aliases = parse_alias(alias_raw)
    return {
        "ready": ready,
        "numeric": numeric,
        "aliases": aliases,
        "num_sha": actual_num,
        "alias_sha": actual_alias,
        "loaded_at": time.time(),
    }


STATE = load_state()


def auth_ok(headers) -> bool:
    if not API_TOKEN:
        return False
    auth = headers.get("Authorization", "")
    key = headers.get("X-API-Key", "")
    supplied = auth[7:] if auth.startswith("Bearer ") else key
    return bool(supplied) and hmac.compare_digest(supplied, API_TOKEN)


def lookup(query: str):
    ready = STATE["ready"]
    if ready.get("status") != "READY" or ready.get("quick_check_ready") is not True:
        return {"status": "BLOCKED", "reason": "READY_NOT_CURRENT", "query": query, "fallback_allowed": False}

    if is_numeric_query(query):
        route = "TIER0A_NUMERIC"
        key = query.strip()
        rows = STATE["numeric"].get(key, [])
    else:
        route = "TIER0B_NAME_ALIAS"
        key = normalize_name(query)
        rows = STATE["aliases"].get(key, [])

    profiles = sorted({r.get("profile_id") for r in rows if r.get("profile_id")})
    if len(profiles) == 1 and rows:
        r = rows[0]
        return {
            "status": "HIT",
            "route": route,
            "query": query,
            "normalized_key": key,
            "profile_id": profiles[0],
            "quickcheck": r.get("quickcheck", ""),
            "related": r.get("related", ""),
            "fallback_allowed": False,
            "ready": {
                "schema": ready.get("schema"),
                "generated_utc": ready.get("generated_utc"),
                "master_version": ready.get("master_version"),
                "service_master_sha256": ready.get("service_master_sha256"),
                "fast_lookup_build_id": ready.get("fast_lookup_build_id"),
                "batch_id": ready.get("upload_batch", {}).get("batch_id"),
            },
        }
    if len(profiles) > 1:
        return {
            "status": "BLOCKED",
            "reason": "AMBIGUOUS_EXACT",
            "route": route,
            "query": query,
            "normalized_key": key,
            "profile_ids": profiles,
            "fallback_allowed": False,
        }
    return {
        "status": "MISS",
        "reason": "TIER0_MISS",
        "route": route,
        "query": query,
        "normalized_key": key,
        "fallback_allowed": False,
    }


MCP_PROTOCOL_VERSION = "2025-06-18"

def mcp_tool_result(payload):
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
        "structuredContent": payload,
        "isError": False,
    }

def mcp_dispatch(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "sros-tier0", "version": "1.2.0"},
                "instructions": "Use quick_check for exact Store #1032 Seafood SROS Tier-0 lookups. No fallback discovery and no query-time calculations."
            }
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {"tools": [{
                "name": "quick_check",
                "title": "SROS Seafood Quick Check",
                "description": "Exact Store #1032 Seafood Tier-0 lookup by UPC, article, family, item name, or alias. Returns only precomputed data; never falls back to raw files or query-time calculations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"q": {"type": "string", "description": "Exact UPC, article, family, item name, or alias"}},
                    "required": ["q"],
                    "additionalProperties": False
                }
            }]}
        }
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != "quick_check":
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Unknown tool"}}
        q = str(args.get("q", "")).strip()
        if not q:
            return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32602, "message": "q is required"}}
        return {"jsonrpc": "2.0", "id": rid, "result": mcp_tool_result(lookup(q))}
    if method and method.startswith("notifications/"):
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}}


class Handler(BaseHTTPRequestHandler):
    server_version = "SROS-Tier0/1.2"

    def log_message(self, fmt, *args):
        print("http", self.address_string(), fmt % args, flush=True)

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/mcp":
            self.send_json(404, {"status": "NOT_FOUND"})
            return
        if not auth_ok(self.headers):
            self.send_json(401, {"status": "UNAUTHORIZED"})
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            req = json.loads(self.rfile.read(n) if n else b"{}")
            result = mcp_dispatch(req)
            if result is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_json(200, result)
        except Exception as e:
            self.send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid request"}})

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/health":
            r = STATE["ready"]
            self.send_json(200, {
                "status": "ok",
                "service": "sros-tier0",
                "quick_check_ready": True,
                "master_version": r.get("master_version"),
                "fast_lookup_build_id": r.get("fast_lookup_build_id"),
                "numeric_keys": len(STATE["numeric"]),
                "alias_keys": len(STATE["aliases"]),
            })
            return
        if u.path == "/ready":
            if not auth_ok(self.headers):
                self.send_json(401, {"status": "UNAUTHORIZED"})
                return
            self.send_json(200, STATE["ready"])
            return
        if u.path == "/quick-check":
            if not auth_ok(self.headers):
                self.send_json(401, {"status": "UNAUTHORIZED"})
                return
            q = parse_qs(u.query).get("q", [""])[0].strip()
            if not q:
                self.send_json(400, {"status": "BAD_REQUEST", "reason": "QUERY_REQUIRED"})
                return
            self.send_json(200, lookup(q))
            return
        self.send_json(404, {"status": "NOT_FOUND"})


if __name__ == "__main__":
    if not API_TOKEN:
        raise SystemExit("SROS_API_TOKEN is required")
    print(json.dumps({
        "event": "startup",
        "service": "sros-tier0",
        "port": PORT,
        "master_version": STATE["ready"].get("master_version"),
        "fast_lookup_build_id": STATE["ready"].get("fast_lookup_build_id"),
        "numeric_keys": len(STATE["numeric"]),
        "alias_keys": len(STATE["aliases"]),
    }), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
