/*
 * Foundryx web chat loader (plan 34 / A7b, D-A7B-2/D-A7B-3).
 *
 * Hand-written, dependency-free, no build step. Served by
 * `routers/webchat_widget.py` with exactly TWO plain string substitutions -
 * the widget key and the panel origin placeholders below - and NOTHING else
 * that is tenant-identifying (no tenant slug, no tenant name, no secret, no
 * origin list, no branding, D-A7B-12): all real configuration comes from
 * the (uncacheable) session endpoint the panel calls once it loads. (The
 * literal placeholder tokens are deliberately not spelled out in THIS
 * comment - the router's replace() is a plain global string replace, so
 * writing them here would substitute inside the comment too.)
 *
 * Mounts ONE fixed-position iframe pointed at the panel (a Next.js public
 * route) and relays a small postMessage protocol so the panel can resize
 * itself and report open/close state. Sets iframe.style.* directly - no
 * <style> element and no stylesheet is injected into the host page
 * (D-A7B-27).
 */
(function () {
  "use strict";

  var WIDGET_KEY = "__WIDGET_KEY__";
  var PANEL_ORIGIN = "__PANEL_ORIGIN__";
  var PANEL_URL = PANEL_ORIGIN + "/public/webchat/" + WIDGET_KEY;
  var LAUNCHER_SIZE = "88px";

  var iframe = document.createElement("iframe");
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

  var isOpen = false;
  var isReady = false;
  var pendingIdentity = null;

  function post(type, payload) {
    if (!iframe.contentWindow) return;
    iframe.contentWindow.postMessage(
      { source: "fx-webchat-loader", type: type, payload: payload || {} },
      PANEL_ORIGIN
    );
  }

  function applyLayout(open, position) {
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

  window.addEventListener("message", function (event) {
    if (event.origin !== PANEL_ORIGIN) return;
    if (event.source !== iframe.contentWindow) return;
    var data = event.data;
    if (!data || data.source !== "fx-webchat-panel") return;
    var position = data.payload && data.payload.position;
    if (data.type === "ready") {
      isReady = true;
      applyLayout(isOpen, position);
      if (pendingIdentity) {
        post("identify", pendingIdentity);
        pendingIdentity = null;
      }
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

  function mount() {
    if (document.body) {
      document.body.appendChild(iframe);
    } else {
      document.addEventListener("DOMContentLoaded", mount);
    }
  }
  mount();

  window.fxWebchat = {
    open: function () {
      post("open");
    },
    close: function () {
      post("close");
    },
    isOpen: function () {
      return isOpen;
    },
    identify: function (identity) {
      if (
        !identity ||
        typeof identity.userRef !== "string" ||
        typeof identity.hash !== "string"
      ) {
        return;
      }
      if (isReady) {
        post("identify", identity);
      } else {
        pendingIdentity = identity;
      }
    }
  };

  if (window.fxChatIdentity) {
    window.fxWebchat.identify(window.fxChatIdentity);
  }
})();
