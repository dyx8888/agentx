(function bootstrapAgentXConnector() {
  if (window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__) {
    return;
  }
  window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__ = true;

  const script = document.createElement("script");
  script.src = chrome.runtime.getURL("src/injected.js");
  script.async = false;
  script.onload = () => script.remove();
  (document.documentElement || document.head || document.body).appendChild(script);

  window.addEventListener("message", async (event) => {
    if (event.source !== window) {
      return;
    }
    if (!event.data || event.data.type !== "AGENTX_CONNECTOR_CAPTURE") {
      return;
    }

    try {
      await chrome.runtime.sendMessage({
        type: "AGENTX_CONNECTOR_CAPTURE",
        payload: event.data.payload
      });
    } catch (_error) {
      // The page hook must never break platform behavior if the extension worker is unavailable.
    }
  });
})();
