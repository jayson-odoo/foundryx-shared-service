/*
 * Foundryx web chat loader (plan 34 / A7b, D-A7B-2/D-A7B-3/D-A7B-11).
 *
 * Hand-written, dependency-free, no build step. Served by
 * `routers/webchat_widget.py` with exactly THREE plain string substitutions -
 * the widget key, the panel origin and the API origin placeholders below -
 * and NOTHING else that is tenant-identifying (no tenant slug, no tenant
 * name, no secret, no origin list, no branding, D-A7B-12): all real
 * configuration comes from the (uncacheable) session endpoint. (The literal
 * placeholder tokens are deliberately not spelled out in THIS comment - the
 * router's replace() is a plain global string replace, so writing them here
 * would substitute inside the comment too.)
 *
 * Amended 2026-09-09 (BL-SS-183) - THE LOADER MINTS THE SESSION.
 * This script runs in the customer's own top-level document, so the browser
 * stamps THAT document's origin on its fetch - the value the channel's
 * allowlist is actually about, and one no other website can forge. The panel
 * cannot do this: a fetch issued from inside the panel iframe always carries
 * the PANEL's origin, so the allowlist could never discriminate between
 * customer websites and the only way to satisfy it was to allowlist the app
 * itself (which let any site embed any channel and let anyone open a chat by
 * navigating straight to the panel URL). So:
 *   1. this script POSTs the session endpoint (with the stored token, and
 *      any host identity assertion) BEFORE any iframe exists;
 *   2. it keeps the visitor token in the HOST page's localStorage, namespaced
 *      per widget key - that IS "one visitor identity per website"
 *      (D-A7B-4), and two tabs of the same site share it (AC-WEB-50);
 *   3. only on success does it mount the iframe, and it hands the whole
 *      session payload to the panel over postMessage with the exact panel
 *      origin as targetOrigin (never a wildcard);
 *   4. an off-list website gets the uniform 404, mounts nothing at all, and
 *      the panel it never loads has no token to chat with.
 *
 * The panel's own document keeps its `frame-ancestors` CSP (clickjacking),
 * and the session endpoint keeps the uniform 404 - the two together are what
 * make a stolen snippet useless off-list.
 *
 * Geometry: ONE fixed-position iframe, `iframe.style.*` set directly - no
 * <style> element and no stylesheet is injected into the host page
 * (D-A7B-27).
 */
(function () {
  "use strict";

  var WIDGET_KEY = "__WIDGET_KEY__";
  var PANEL_ORIGIN = "__PANEL_ORIGIN__";
  var API_ORIGIN = "__API_ORIGIN__";
  var PANEL_URL = PANEL_ORIGIN + "/public/webchat/" + WIDGET_KEY;
  var SESSION_URL =
    API_ORIGIN + "/public/omnichannel/webchat/" + WIDGET_KEY + "/session";
  var STORAGE_KEY = "fx-webchat-token:" + WIDGET_KEY;
  var LAUNCHER_SIZE = "88px";

  var iframe = null;
  var session = null;
  var isOpen = false;
  var isReady = false;
  var wantsOpen = false;

  /* AC-WEB-49 - a browser that blocks storage (private mode, a blocked
   * partitioned store) keeps its token here instead: the visitor still
   * chats for the life of the page, nothing throws, nothing is shown. */
  var memoryToken = null;

  function readToken() {
    try {
      var stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored) return stored;
    } catch (e) {
      /* storage unavailable - fall through to the in-memory copy */
    }
    return memoryToken;
  }

  function writeToken(token) {
    memoryToken = token;
    try {
      window.localStorage.setItem(STORAGE_KEY, token);
    } catch (e) {
      /* storage unavailable - the in-memory copy above is the fallback */
    }
  }

  function positionOf(payload) {
    var config = payload && payload.config;
    var appearance = config && config.appearance;
    return (appearance && appearance.position) || "right";
  }

  function post(type, payload) {
    if (!iframe || !iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { source: "fx-webchat-loader", type: type, payload: payload || {} },
      PANEL_ORIGIN
    );
  }

  function applyLayout(open, position) {
    if (!iframe) return;
    var style = iframe.style;
    if (position === "left") {
      style.left = "0px";
      style.right = "";
    } else {
      style.left = "";
      style.right = "0px";
    }
    if (open) {
      style.width = "min(400px, 100vw)";
      style.height = "min(640px, 100vh)";
    } else {
      style.width = LAUNCHER_SIZE;
      style.height = LAUNCHER_SIZE;
    }
  }

  function mount() {
    if (iframe) return;
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", mount);
      return;
    }
    iframe = document.createElement("iframe");
    iframe.src = PANEL_URL;
    iframe.title = "Chat";
    iframe.setAttribute("allow", "clipboard-write");
    iframe.setAttribute("allowtransparency", "true");

    var style = iframe.style;
    style.position = "fixed";
    style.bottom = "0px";
    style.right = "0px";
    style.left = "";
    style.width = LAUNCHER_SIZE;
    style.height = LAUNCHER_SIZE;
    style.border = "0";
    style.background = "transparent";
    style.colorScheme = "light";
    style.zIndex = "2147483000";

    applyLayout(false, positionOf(session));
    document.body.appendChild(iframe);
  }

  /* The ONE network call this script makes. A failure of any kind (off-list
   * origin, dead widget key, offline network) is silent: no iframe, no
   * console noise, nothing rendered on the customer's page. */
  function startSession(identity) {
    if (typeof window.fetch !== "function") return;
    var body = {};
    var stored = readToken();
    if (stored) body.token = stored;
    if (identity) body.identity = identity;
    window
      .fetch(SESSION_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      })
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (payload) {
        if (!payload || typeof payload.token !== "string") return;
        session = payload;
        writeToken(payload.token);
        mount();
        if (isReady) {
          post("session", session);
          applyLayout(isOpen, positionOf(session));
        }
      })
      .catch(function () {
        /* silent - see above */
      });
  }

  window.addEventListener("message", function (event) {
    if (event.origin !== PANEL_ORIGIN) return;
    if (!iframe || event.source !== iframe.contentWindow) return;
    var data = event.data;
    if (!data || data.source !== "fx-webchat-panel") return;
    var position =
      (data.payload && data.payload.position) || positionOf(session);
    if (data.type === "ready") {
      isReady = true;
      if (session) post("session", session);
      if (wantsOpen) {
        wantsOpen = false;
        post("open");
      }
      applyLayout(isOpen, position);
    } else if (data.type === "resize") {
      applyLayout(isOpen, position);
    } else if (data.type === "opened") {
      isOpen = true;
      applyLayout(true, position);
    } else if (data.type === "closed") {
      isOpen = false;
      applyLayout(false, position);
    }
  });

  window.fxWebchat = {
    open: function () {
      if (isReady) post("open");
      else wantsOpen = true;
    },
    close: function () {
      wantsOpen = false;
      post("close");
    },
    isOpen: function () {
      return isOpen;
    },
    /* D-A7B-9 - re-mints the session with the customer's server-signed
     * assertion and hands the new one to the panel. An invalid hash is
     * ignored server-side and the session simply stays anonymous. */
    identify: function (identity) {
      if (
        !identity ||
        typeof identity.userRef !== "string" ||
        typeof identity.hash !== "string"
      ) {
        return;
      }
      startSession(identity);
    }
  };

  var bootIdentity = null;
  if (
    window.fxChatIdentity &&
    typeof window.fxChatIdentity.userRef === "string" &&
    typeof window.fxChatIdentity.hash === "string"
  ) {
    bootIdentity = window.fxChatIdentity;
  }
  startSession(bootIdentity);
})();
