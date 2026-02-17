document.body.addEventListener("htmx:afterRequest", (event) => {
  const status = event.detail.xhr.status;
  const path = event.detail.pathInfo?.requestPath || "";

  if (path.startsWith("/ui/") && status >= 200 && status < 300) {
    htmx.trigger("body", "refresh");
  }
});

document.body.addEventListener("htmx:responseError", (event) => {
  const xhr = event.detail.xhr;
  if (!xhr) return;
  let detail = "";
  try {
    const parsed = JSON.parse(xhr.responseText);
    detail = parsed.detail || "";
  } catch {
    detail = xhr.responseText || "";
  }

  if (xhr.status === 429) {
    alert(detail || "Refresh cooldown active.");
    return;
  }

  if (xhr.status === 400) {
    alert(detail || "Bad request. Check connector configuration.");
    return;
  }

  alert(detail || `Request failed (${xhr.status}).`);
});
