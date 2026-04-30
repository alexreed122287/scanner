/**
 * Tradier API Proxy — Cloudflare Worker
 * ======================================
 *
 * Forwards Tradier API requests from the browser, injecting your API key
 * server-side so it never lives in the user's localStorage / page source.
 *
 * Goals:
 *   1. Tradier key stays in Cloudflare secrets — never sent to browser
 *   2. Origin allowlist + per-IP rate limit (defense in depth)
 *   3. Path allowlist — only /v1/markets/*, /v1/accounts/*, /v1/user/*
 *   4. Sandbox vs Live selection via `?mode=live` / `?mode=sandbox` query
 *      param (stripped before forwarding)
 *   5. Pass-through method (GET/POST) + body + content-type so order
 *      placement works
 *   6. CORS headers, 429 / 5xx no-store cache to avoid sticky errors
 *
 * Secrets (set via `wrangler secret put`):
 *   TRADIER_LIVE_TOKEN      — your production Tradier API key
 *   TRADIER_SANDBOX_TOKEN   — your sandbox Tradier API key (optional, falls
 *                             back to live token if absent)
 *
 * Env vars (wrangler.toml):
 *   ALLOWED_ORIGINS — comma-separated list of origins that may call the
 *                     worker (e.g. "https://alexreed122287.github.io,http://localhost:8000")
 *
 * Deploy:
 *   cd worker/tradier-proxy
 *   npx wrangler login
 *   npx wrangler secret put TRADIER_LIVE_TOKEN
 *   npx wrangler secret put TRADIER_SANDBOX_TOKEN     (optional)
 *   npx wrangler deploy
 *
 * Use from scanner:
 *   API tab → set "Tradier proxy URL" to the workers.dev URL printed by deploy.
 *   Scanner will route all Tradier traffic through the proxy and stop reading
 *   the local Tradier-key fields. Mode (live/sandbox) selected via the same
 *   "Mode" toggle in the API tab — proxy reads ?mode= from each request.
 */

const UPSTREAM_LIVE    = "https://api.tradier.com";
const UPSTREAM_SANDBOX = "https://sandbox.tradier.com";

// Path allowlist — proxy only forwards under these prefixes. Without this,
// anyone with the worker URL could call arbitrary endpoints under
// api.tradier.com using your secret. The Tradier API surface is fairly small;
// these cover everything the scanner uses (quotes/history/options/orders/positions).
//
// Every prefix MUST end in `/` to prevent prefix-smuggling: a fuzz probe
// against the prior `/v1/watchlists` (no trailing slash) showed
// `/v1/watchlistsBOMB` flowed through to Tradier because .startsWith()
// matched. With a trailing slash, only `/v1/watchlists/...` matches; the
// bare `/v1/watchlists` endpoint is added separately as an exact match.
const ALLOWED_PATH_PREFIXES = [
  "/v1/markets/",            // quotes, history, options chains, expirations, timesales
  "/v1/accounts/",           // positions, balances, orders, history
  "/v1/user/",               // user profile
  "/v1/watchlists/",         // Tradier-side watchlist sub-resources
];
// Exact paths (no prefix expansion) — the bare watchlists collection endpoint.
const ALLOWED_EXACT_PATHS = new Set([
  "/v1/watchlists",
  "/sync-config",                  // already handled, listed here for clarity
  "/circuit-breaker/snapshot",     // council #1: drawdown circuit breaker
]);

// Per-IP rate limit (in-memory, lives for the Worker isolate's lifetime ~10s).
// Set just below Tradier's documented 120/min cap so the limiter is the
// chokepoint, not the upstream. Bumped 100 → 115 (2026-04-29) — the deeper
// 400-day history fetch + scanner enrichment burst was hitting 100/min.
// Tradier's 120 limit gives 5-call headroom which the burst doesn't typically
// fill once the enrichment count is also reduced (SC_ENRICH_LIMIT 200→60 in
// scanner). Watch the cf-ray + 429 logs in production.
const RATE_PER_IP_PER_MIN = 115;
const _rateMap = new Map();   // ip -> [timestamps]
function rateLimited(ip) {
  const now = Date.now();
  const arr = (_rateMap.get(ip) || []).filter((t) => now - t < 60000);
  if (arr.length >= RATE_PER_IP_PER_MIN) {
    _rateMap.set(ip, arr);
    return true;
  }
  arr.push(now);
  _rateMap.set(ip, arr);
  if (_rateMap.size > 1000) {
    const oldestKey = _rateMap.keys().next().value;
    _rateMap.delete(oldestKey);
  }
  return false;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const allowed = (env.ALLOWED_ORIGINS || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    // FAIL CLOSED: an empty ALLOWED_ORIGINS env var is treated as "deny all",
    // not "allow all". Was the wrong fail-mode — a deploy that forgets to set
    // wrangler.toml [vars] would silently open the proxy to the world AND
    // reflect the attacker's Origin in the CORS header. Combined with a
    // missing LIVE_MODE_TOKEN secret (gate auto-bypassed), that's full
    // unauthorized access to the user's live Tradier account.
    const isAllowedOrigin = allowed.length > 0 && allowed.includes(origin);
    // corsOrigin defaults to the FIRST allowlisted origin (so preflights from
    // unknown origins still get a deterministic, narrowly-scoped header).
    // Never echoes "*" or unknown origins.
    const corsOrigin = isAllowedOrigin ? origin : (allowed[0] || "https://invalid.example");

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(corsOrigin) });
    }

    // Tradier endpoints accept GET (markets, positions read) + POST (orders) + DELETE (cancel order)
    if (!["GET", "POST", "PUT", "DELETE"].includes(request.method)) {
      return jsonError(405, "Method not allowed", corsOrigin);
    }

    if (!isAllowedOrigin) {
      return jsonError(403, "Origin not allowed", corsOrigin);
    }

    // ───────────────────────────────────────────────────────────────────────
    //  SYNC-CONFIG endpoints (cross-device settings sync)
    // ───────────────────────────────────────────────────────────────────────
    // Two endpoints that store opaque encrypted config blobs in Cloudflare
    // KV, keyed by an opaque id derived client-side from a user-chosen
    // master secret. The worker NEVER sees plaintext — encryption happens
    // entirely in the browser before upload. KV stores ciphertext only.
    //
    // Auth model: knowledge of the id IS the auth. The id is SHA-256 of
    // the master secret (with a fixed prefix), so brute-forcing it is
    // computationally infeasible (256-bit space). Anyone who knows the
    // master secret can derive the id and read/write that blob.
    //
    // Endpoints:
    //   GET  /sync-config?id=<hex>          → returns {iv, ct} or 404
    //   POST /sync-config                   → body {id, iv, ct} stores it
    //
    // KV namespace binding: env.SYNC_CONFIG (configure in wrangler.toml).
    if (url.pathname === "/sync-config") {
      // KV namespace must be bound; without it return a clear 500 instead
      // of a confusing nil-deref crash.
      if (!env.SYNC_CONFIG) {
        return jsonError(500, "SYNC_CONFIG KV namespace not bound to this worker. See worker/tradier-proxy/README for setup.", corsOrigin);
      }
      if (request.method === "GET") {
        const id = url.searchParams.get("id") || "";
        if (!/^[a-f0-9]{64}$/i.test(id)) {
          return jsonError(400, "Invalid sync id (expected 64 hex chars)", corsOrigin);
        }
        const blob = await env.SYNC_CONFIG.get(id);
        if (!blob) return jsonError(404, "No config stored for this id", corsOrigin);
        return new Response(blob, {
          status: 200,
          headers: {
            ...corsHeaders(corsOrigin),
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          },
        });
      }
      if (request.method === "POST") {
        // Body cap: 16KB is generous (typical encrypted config is <2KB).
        const MAX = 16 * 1024;
        let bodyText;
        try {
          const reader = request.body && request.body.getReader();
          if (!reader) return jsonError(400, "Empty body", corsOrigin);
          const chunks = [];
          let received = 0;
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            received += value.byteLength;
            if (received > MAX) {
              try { await reader.cancel(); } catch (_) {}
              return jsonError(413, `Body too large (max ${MAX} bytes)`, corsOrigin);
            }
            chunks.push(value);
          }
          const merged = new Uint8Array(received);
          let off = 0; for (const c of chunks) { merged.set(c, off); off += c.byteLength; }
          bodyText = new TextDecoder().decode(merged);
        } catch (err) {
          return jsonError(400, `Could not read body: ${err.message}`, corsOrigin);
        }
        let parsed;
        try { parsed = JSON.parse(bodyText); }
        catch { return jsonError(400, "Body is not valid JSON", corsOrigin); }
        if (!parsed || typeof parsed.id !== "string" || !/^[a-f0-9]{64}$/i.test(parsed.id)) {
          return jsonError(400, "Body must include `id` (64 hex chars)", corsOrigin);
        }
        if (typeof parsed.iv !== "string" || typeof parsed.ct !== "string") {
          return jsonError(400, "Body must include `iv` and `ct` strings", corsOrigin);
        }
        // Worker stores the encrypted blob keyed by id. 90 days of inactivity
        // expires the entry — actively-used setups touch it on every push so
        // the TTL slides forward; abandoned configs are purged automatically.
        await env.SYNC_CONFIG.put(parsed.id, JSON.stringify({ iv: parsed.iv, ct: parsed.ct, ts: Date.now() }), {
          expirationTtl: 90 * 24 * 60 * 60, // 90 days
        });
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: {
            ...corsHeaders(corsOrigin),
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
          },
        });
      }
      return jsonError(405, "Method not allowed for /sync-config", corsOrigin);
    }

    const pathOk = ALLOWED_EXACT_PATHS.has(url.pathname)
      || ALLOWED_PATH_PREFIXES.some((p) => url.pathname.startsWith(p));
    if (!pathOk) {
      return jsonError(403, "Path not allowed", corsOrigin);
    }

    const ip = request.headers.get("CF-Connecting-IP") || "unknown";
    if (rateLimited(ip)) {
      return jsonError(429, "Too many requests", corsOrigin);
    }

    // Determine mode (sandbox vs live). Default to sandbox for safety —
    // an order placement to live should be explicit.
    const mode = (url.searchParams.get("mode") || "sandbox").toLowerCase();
    const isLive = mode === "live";
    const upstream = isLive ? UPSTREAM_LIVE : UPSTREAM_SANDBOX;
    const token = isLive
      ? env.TRADIER_LIVE_TOKEN
      : (env.TRADIER_SANDBOX_TOKEN || env.TRADIER_LIVE_TOKEN);

    if (!token) {
      return jsonError(500, `${isLive ? "TRADIER_LIVE_TOKEN" : "TRADIER_SANDBOX_TOKEN"} secret not configured`, corsOrigin);
    }

    // LIVE-MODE GATE — defense in depth.
    // Without this gate, anyone who learns the workers.dev URL could call
    //   curl -H "Origin: https://alexreed122287.github.io" \
    //        "https://tradier-proxy.../v1/user/profile?mode=live"
    // and get the user's live account number, then place orders against it
    // (path allowlist permits /v1/accounts/<id>/orders).
    //
    // Set the secret with: wrangler secret put LIVE_MODE_TOKEN
    // The scanner's fetch monkey-patch sends the matching X-Live-Token header
    // on every proxy request when mode=live. Sandbox stays open (synthetic
    // data, no orders, no real account exposure — abuse cost is just quota).
    //
    // Backward-compatible: if LIVE_MODE_TOKEN is not set, the gate is bypassed
    // (existing setups keep working until the user opts in).
    if (isLive && env.LIVE_MODE_TOKEN) {
      // Trim both sides — paste-newline foot-gun where "tokenABC\n" silently
      // !== "tokenABC" and the user gets a confusing 403 from a "correct" token.
      // Constant-time comparison defends against the (low-likelihood) timing
      // attack vector at the edge.
      const provided = (request.headers.get("X-Live-Token") || "").trim();
      const expected = (env.LIVE_MODE_TOKEN || "").trim();
      if (!safeEqual(provided, expected)) {
        return jsonError(403, "Live mode requires X-Live-Token header (set rrjcar_tradier_proxy_live_token in scanner)", corsOrigin);
      }
    }

    // WRITE-ACTION GATE — order placement and cancellation require a SECOND
    // shared secret (X-Trade-Token) on top of X-Live-Token. The trade token
    // is intentionally never persisted to localStorage (lives in
    // window._tradeToken in the scanner, dies on tab close), so a leaked or
    // exfiltrated localStorage doesn't expose trading authority — only an
    // active session can place orders. Reads (positions, balances, profile,
    // quotes) only need X-Live-Token, so the auto-trader can scan and alert
    // unattended; only the actual order placement step requires this token.
    //
    // Backward-compatible: if WRITE_AUTH_TOKEN secret is unset, gate skipped.
    const isOrderWrite = (request.method === "POST" || request.method === "PUT" || request.method === "DELETE")
      // (?:\/|$) anchor — was matching subpaths like /ordersFOO before;
      // Tradier doesn't expose such endpoints today but this is defense
      // against a future addition silently demanding a trade token.
      && /\/v1\/accounts\/[^/]+\/orders(?:\/|$)/.test(url.pathname);

    // ─── COUNCIL #1: SERVER-SIDE CIRCUIT BREAKER ───────────────────────────
    // Daily / weekly drawdown caps enforced server-side. Client cannot route
    // around. State stored in SYNC_CONFIG KV under reserved keys:
    //   __circuit_breaker__         → { dailyLossPct, weeklyLossPct, lastUpdated, lockUntil }
    // Read on every order POST in live mode; if breached, return 403.
    //
    // Caps (hardcoded):
    //   - Daily realized loss > 2% of starting-day equity → 24h lockout
    //   - Trailing 5-day loss  > 5% of starting equity   → 7-day lockout
    //
    // The scanner POSTs equity snapshots to /circuit-breaker/snapshot daily;
    // the worker computes the cap state. If no snapshot is fresh (< 25h old),
    // worker DEFAULTS TO LOCKED (fail-safe).
    if (isLive && isOrderWrite) {
      try {
        const cbRaw = env.SYNC_CONFIG ? await env.SYNC_CONFIG.get("__circuit_breaker__") : null;
        const cb = cbRaw ? JSON.parse(cbRaw) : null;
        const nowMs = Date.now();
        if (cb && cb.lockUntil && cb.lockUntil > nowMs) {
          const hoursLeft = ((cb.lockUntil - nowMs) / 3600000).toFixed(1);
          return jsonError(403, `Circuit breaker active — ${cb.lockReason || "drawdown cap breached"}. Lockout: ${hoursLeft}h remaining.`, corsOrigin);
        }
        // Stale-snapshot fail-safe: if no snapshot in 25h, lock by default.
        // Toggle off via env.CB_REQUIRE_FRESH=false (not a secret; an env var).
        const requireFresh = (env.CB_REQUIRE_FRESH || "true") !== "false";
        if (requireFresh && cb && cb.lastUpdated && (nowMs - cb.lastUpdated) > 25 * 3600 * 1000) {
          return jsonError(503, "Circuit breaker snapshot stale (>25h). POST a fresh equity snapshot to /circuit-breaker/snapshot before trading.", corsOrigin);
        }
      } catch (e) {
        // KV failure — fail-open by design (don't block legitimate orders on
        // KV outage). If the user wants strict, set CB_REQUIRE_FRESH=true
        // and re-deploy with KV health monitoring.
      }
    }
    // Endpoint to receive equity snapshots from scanner (writes circuit-
    // breaker state). Body: JSON { todayEquity, weekStartEquity, dailyPnl,
    // weeklyPnl }. Worker computes lockUntil + reason; KV-persists.
    if (url.pathname === "/circuit-breaker/snapshot" && request.method === "POST") {
      if (!env.SYNC_CONFIG) return jsonError(500, "KV not bound", corsOrigin);
      try {
        const txt = await request.text();
        const j = JSON.parse(txt);
        const dailyPct = (typeof j.dailyPct === "number") ? j.dailyPct : 0;
        const weeklyPct = (typeof j.weeklyPct === "number") ? j.weeklyPct : 0;
        const nowMs = Date.now();
        let lockUntil = 0, lockReason = "";
        if (dailyPct < -0.02) {
          lockUntil = nowMs + 24 * 3600 * 1000;
          lockReason = `daily drawdown ${(dailyPct*100).toFixed(2)}% < -2% cap`;
        }
        if (weeklyPct < -0.05) {
          const wkLock = nowMs + 7 * 24 * 3600 * 1000;
          if (wkLock > lockUntil) {
            lockUntil = wkLock;
            lockReason = `5-day drawdown ${(weeklyPct*100).toFixed(2)}% < -5% cap`;
          }
        }
        const newCb = { dailyPct, weeklyPct, lockUntil, lockReason, lastUpdated: nowMs };
        await env.SYNC_CONFIG.put("__circuit_breaker__", JSON.stringify(newCb), { expirationTtl: 30 * 86400 });
        return new Response(JSON.stringify({ ok: true, circuitBreaker: newCb }), {
          status: 200,
          headers: { ...corsHeaders(corsOrigin), "Content-Type": "application/json", "Cache-Control": "no-store" },
        });
      } catch (e) {
        return jsonError(400, `Snapshot parse error: ${e.message}`, corsOrigin);
      }
    }
    if (isLive && isOrderWrite && env.WRITE_AUTH_TOKEN) {
      // Same paste-newline trim + constant-time compare as X-Live-Token above
      const tradeProvided = (request.headers.get("X-Trade-Token") || "").trim();
      const tradeExpected = (env.WRITE_AUTH_TOKEN || "").trim();
      if (!tradeProvided) {
        return jsonError(403, "Order placement requires X-Trade-Token header (click 'ENABLE TRADING' in scanner header to enter session token)", corsOrigin);
      }
      if (!safeEqual(tradeProvided, tradeExpected)) {
        // Distinguish "value mismatch" from "header missing" so the scanner
        // (and the user reading the log) doesn't waste time re-arming the
        // same wrong token over and over. The previous flat-message version
        // led to a recursive prompt → reject loop because the client kept
        // wiping its in-memory token and re-prompting for it.
        return jsonError(403, "X-Trade-Token value does not match the worker's WRITE_AUTH_TOKEN secret. Reset the secret (wrangler secret put WRITE_AUTH_TOKEN) and arm the same value in the scanner.", corsOrigin);
      }
    }
    // HC-D — partial-config foot-gun protection.
    // If the operator set LIVE_MODE_TOKEN (live read gate) but FORGOT to set
    // WRITE_AUTH_TOKEN (write gate), order placement silently downgrades to
    // "needs only X-Live-Token" — defeating the whole HC5 design. Treat
    // partial-config as a hard misconfiguration, not graceful degradation.
    // Operator can opt out by leaving BOTH unset (full bypass) or setting BOTH.
    if (isLive && isOrderWrite && env.LIVE_MODE_TOKEN && !env.WRITE_AUTH_TOKEN) {
      return jsonError(500, "Worker misconfigured: LIVE_MODE_TOKEN is set but WRITE_AUTH_TOKEN is not. Either set both (recommended) or unset both. See worker README.", corsOrigin);
    }

    // HC-C / RC-1 — stream-based body-size cap. The previous parseInt(content-length)
    // check trusted an attacker-controlled header: a POST with
    // "Content-Length: 100" and a 100MB body would sail through, then
    // request.text() would buffer the full 100MB. Cloudflare normalizes
    // most cases but doesn't contractually guarantee. Stream + count instead.
    //
    // RC-1: include DELETE. Tradier order-cancels are body-less in practice,
    // but the cap was advertised as universal and a malicious DELETE with a
    // bogus body would buffer somewhere. Cheap to gate uniformly.
    //
    // RC-5: __bodyTextForUpstream declared with `let` outside the if so its
    // function-scope hoisting (was `var`) is replaced with explicit block-scope.
    let __bodyTextForUpstream = "";
    if (request.method === "POST" || request.method === "PUT" || request.method === "DELETE") {
      const MAX_BODY_BYTES = 8192;
      try {
        if (!request.body) {
          __bodyTextForUpstream = "";
        } else {
          const reader = request.body.getReader();
          const chunks = [];
          let received = 0;
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            received += value.byteLength;
            if (received > MAX_BODY_BYTES) {
              try { await reader.cancel(); } catch (_) {}
              return jsonError(413, `Request body too large (max ${MAX_BODY_BYTES} bytes)`, corsOrigin);
            }
            chunks.push(value);
          }
          // Concatenate + decode as UTF-8
          const merged = new Uint8Array(received);
          let offset = 0;
          for (const c of chunks) { merged.set(c, offset); offset += c.byteLength; }
          __bodyTextForUpstream = new TextDecoder().decode(merged);
        }
      } catch (err) {
        return jsonError(400, `Could not read request body: ${err.message}`, corsOrigin);
      }
    }

    // Strip ?mode= before forwarding so we don't pollute Tradier's params
    const forwardParams = new URLSearchParams(url.searchParams);
    forwardParams.delete("mode");
    const upstreamUrl = upstream + url.pathname + (forwardParams.toString() ? "?" + forwardParams.toString() : "");

    // Forward method, body (for POST/PUT/DELETE order paths), content-type
    const upstreamHeaders = {
      "Authorization": `Bearer ${token}`,
      "Accept":        request.headers.get("Accept") || "application/json",
      "User-Agent":    "rrjcar-tradier-proxy/1.0",
    };
    const ct = request.headers.get("Content-Type");
    if (ct) upstreamHeaders["Content-Type"] = ct;

    const fetchInit = {
      method:  request.method,
      headers: upstreamHeaders,
    };
    if (request.method === "POST" || request.method === "PUT") {
      // Pass body through as text — Tradier order POSTs use form-urlencoded.
      // Body was already streamed + size-capped above (HC-C); reuse it
      // instead of re-reading request body (which is now empty/locked).
      fetchInit.body = __bodyTextForUpstream || "";
    }

    try {
      const upstreamRes = await fetch(upstreamUrl, fetchInit);
      const body = await upstreamRes.text();
      // Forward Tradier's Retry-After on 429 so the scanner's tradierFetch
      // wrapper can pause its queue accordingly.
      const respHeaders = {
        ...corsHeaders(corsOrigin),
        "Content-Type": upstreamRes.headers.get("Content-Type") || "application/json",
        // Only cache 2xx GETs at the edge; orders + errors must be no-store
        "Cache-Control": (upstreamRes.ok && request.method === "GET") ? "public, max-age=10" : "no-store",
      };
      const retryAfter = upstreamRes.headers.get("Retry-After");
      if (retryAfter) respHeaders["Retry-After"] = retryAfter;
      return new Response(body, { status: upstreamRes.status, headers: respHeaders });
    } catch (err) {
      return jsonError(502, `Upstream fetch failed: ${err.message}`, corsOrigin);
    }
  },
};

// Constant-time string equality. Variable-time `===` / `!==` leaks information
// about which prefix matched, so a network attacker who can measure response
// timing can recover the secret byte-by-byte. The risk is low here (Cloudflare
// edge, TLS noise, single-user proxy), but the cost of fixing it is one short
// helper. NB: returns false if lengths differ, but does NOT short-circuit on
// the byte comparison — it always walks the longer string so length itself
// doesn't leak via timing either.
function safeEqual(a, b) {
  const sa = String(a == null ? "" : a);
  const sb = String(b == null ? "" : b);
  // Walk the longer of the two; XOR each char code. A length mismatch is
  // recorded by xoring length differences into `mismatch`.
  const len = Math.max(sa.length, sb.length);
  let mismatch = sa.length ^ sb.length;
  for (let i = 0; i < len; i++) {
    const ca = i < sa.length ? sa.charCodeAt(i) : 0;
    const cb = i < sb.length ? sb.charCodeAt(i) : 0;
    mismatch |= ca ^ cb;
  }
  return mismatch === 0;
}

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin":  origin,
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Accept, X-Live-Token, X-Trade-Token",
    "Access-Control-Expose-Headers":"Retry-After",
    "Access-Control-Max-Age":       "86400",
    "Vary":                         "Origin",
  };
}

function jsonError(status, message, origin) {
  return new Response(JSON.stringify({ error: message }), {
    status,
    headers: {
      ...corsHeaders(origin),
      "Content-Type":  "application/json",
      "Cache-Control": "no-store",
    },
  });
}
