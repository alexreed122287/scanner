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
const ALLOWED_PATH_PREFIXES = [
  "/v1/markets/",            // quotes, history, options chains, expirations, timesales
  "/v1/accounts/",           // positions, balances, orders, history
  "/v1/user/",               // user profile
  "/v1/watchlists",          // (optional) Tradier-side watchlists
];

// Per-IP rate limit (in-memory, lives for the Worker isolate's lifetime ~10s).
// Set just below Tradier's documented 120/min cap so the limiter is the
// chokepoint, not the upstream.
const RATE_PER_IP_PER_MIN = 100;
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

    if (!ALLOWED_PATH_PREFIXES.some((p) => url.pathname.startsWith(p))) {
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
      const provided = (request.headers.get("X-Live-Token") || "").trim();
      const expected = (env.LIVE_MODE_TOKEN || "").trim();
      if (provided !== expected) {
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
    if (isLive && isOrderWrite && env.WRITE_AUTH_TOKEN) {
      // Same paste-newline trim as X-Live-Token above
      const tradeProvided = (request.headers.get("X-Trade-Token") || "").trim();
      const tradeExpected = (env.WRITE_AUTH_TOKEN || "").trim();
      if (tradeProvided !== tradeExpected) {
        return jsonError(403, "Order placement requires X-Trade-Token header (click 'ENABLE TRADING' in scanner header to enter session token)", corsOrigin);
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
