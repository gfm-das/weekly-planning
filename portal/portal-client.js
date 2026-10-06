/*
 * portal-client.js: small helpers that every portal page inside the shell's frame shares.
 *
 * Who uses it: home.html (Overview), planning.html, callins.html, calendar.html, announcements.html,
 * archetypes.html and archetype-settings.html. Each loads it with <script src="portal-client.js">.
 *
 * What it gives the page (all on window):
 *   portalAPI(path, options)             a request to portal-api (/api/<path>) with a fresh sign-in token
 *   escapeHTML(text)                     text made safe to put inside HTML
 *   portalAttachment(id, name)           downloads an attachment of an event or announcement
 *   uploadPortalFiles(table, id, files)  adds files to an event or announcement (16 MB each at most)
 *   portalConfirm({...})                 asks "are you sure?" in the page before something is deleted
 *
 * How it fits: the shell (index.html) opens the page with ?portal_token=… in the address. This file takes the token
 * out of the address at once (so it is not kept in the history or shown on screen) and, for every request, asks the
 * shell for a token that is still valid (ensureMissionSession in portal-session.js). The shell also tells the page
 * the theme and the language with messages ("portal-theme", "mission-language").
 */
(() => {
  // ---- Messages from the shell ----------------------------------------------------------------------------------
  addEventListener("message", (event) => {
    if (event.data?.type === "portal-theme") {
      document.documentElement.dataset.theme = event.data.theme || "mission";
    }
    // i18n.js sets lang and dir itself; this is for a page without it.
    if (event.data?.type === "mission-language" && !window.MissionI18n) {
      document.documentElement.lang = event.data.language || "en";
    }
  });

  // ---- The sign-in token ----------------------------------------------------------------------------------------
  // The token the shell put into the address, or the one saved in this browser. The address is cleaned at once
  // (the whole query string goes; a page that needs its own part of it reads it before this file loads).
  const query = new URLSearchParams(location.search);
  const addressToken = query.get("portal_token") || localStorage.getItem("mission_access_token");
  if (query.has("portal_token")) {
    history.replaceState({}, "", location.pathname + location.hash);
  }

  // A token that is still valid: the shell renews one that is about to run out (a laptop that slept, a long
  // meeting). A page opened on its own, without the shell, uses the saved one.
  async function currentToken() {
    if (window.parent.ensureMissionSession) return await window.parent.ensureMissionSession();
    return localStorage.getItem("mission_access_token") || addressToken;
  }

  // The chosen interface language, so the API can open Church links in it (lang= on churchofjesuschrist.org).
  function interfaceLanguage() {
    return window.MissionI18n?.state.language || document.documentElement.lang || "en";
  }

  // ---- Requests to portal-api -----------------------------------------------------------------------------------
  // options are fetch() options; a plain object in options.body is sent as JSON (a FormData as it is). Throws an
  // Error with the server's message, its HTTP status (error.status) and per-field messages (error.fields).
  window.portalAPI = async (path, options = {}) => {
    const headers = {
      Authorization: "Bearer " + (await currentToken()),
      "X-Mission-Language": interfaceLanguage(),
      ...options.headers,
    };
    if (options.body && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }
    const response = await fetch("/api/" + path, { ...options, headers, cache: "no-store" });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = Error(data.error || "The request could not be completed.");
      error.status = response.status;
      error.fields = data.fields || null; // per-field messages, e.g. from the add-person form
      throw error;
    }
    return response.json();
  };

  // ---- Safe text in HTML ----------------------------------------------------------------------------------------
  const HTML_ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  window.escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => HTML_ESCAPES[character]);

  // ---- Attachments ----------------------------------------------------------------------------------------------
  // Downloads the file with the sign-in (a plain link could not send it) and saves it under its own name.
  window.portalAttachment = async (id, name) => {
    const response = await fetch("/api/attachments/" + id, {
      headers: { Authorization: "Bearer " + (await currentToken()) },
      cache: "no-store",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw Error(data.error || "This attachment is unavailable.");
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  };

  // Files already added are remembered, so trying again after a failed upload does not add them twice.
  const uploadedFiles = new WeakSet();
  const UPLOAD_LIMIT = 16 * 1024 * 1024; // the same limit as nginx (client_max_body_size) and portal-api

  // table is "events" or "announcements"; id is the event's or announcement's id.
  window.uploadPortalFiles = async (table, id, files) => {
    for (const file of files) {
      if (uploadedFiles.has(file)) continue;
      if (file.size > UPLOAD_LIMIT) throw Error(`“${file.name}” is larger than 16 MB. Choose a smaller file.`);
      const body = new FormData();
      body.append("file", file);
      try {
        await portalAPI(`${table}/${id}/attachments`, { method: "POST", body });
      } catch (e) {
        throw Error(`“${file.name}” was not added: ${e.message}`);
      }
      uploadedFiles.add(file);
    }
  };

  // ---- "Are you sure?" before deleting --------------------------------------------------------------------------
  function paragraph(text, className) {
    const line = document.createElement("p");
    if (className) line.className = className;
    line.textContent = text;
    return line;
  }

  function dialogButton(label, className, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.onclick = onClick;
    return button;
  }

  // A confirmation inside the page (not the browser's own box, which cannot be translated or styled).
  //   title, message: plain interface text (i18n.js translates it)
  //   name: the item's own name (never translated)
  //   choices: [{ value, label }], one red button each
  //   keep: the label of the button that changes nothing (default "Cancel")
  // Resolves to the chosen value, or "" when cancelled (that button, or Esc).
  window.portalConfirm = ({ title, name = "", message = "", choices, keep = "Cancel" }) =>
    new Promise((resolve) => {
      const dialog = document.createElement("dialog");
      dialog.className = "confirm-dialog";

      const heading = document.createElement("h2");
      heading.id = "confirm-" + Date.now();
      heading.textContent = title;
      dialog.setAttribute("aria-labelledby", heading.id);
      dialog.append(heading);

      if (name) {
        const nameLine = paragraph(name, "confirm-name");
        nameLine.setAttribute("data-i18n-ignore", "");
        dialog.append(nameLine);
      }
      if (message) dialog.append(paragraph(message));

      const actions = document.createElement("div");
      actions.className = "dialog-actions confirm-actions";
      const cancel = dialogButton(keep, "secondary", () => dialog.close(""));
      actions.append(cancel);
      for (const choice of choices) {
        actions.append(dialogButton(choice.label, "danger", () => dialog.close(choice.value)));
      }
      dialog.append(actions);

      dialog.addEventListener("close", () => {
        dialog.remove();
        resolve(dialog.returnValue || "");
      });
      document.body.append(dialog);
      dialog.showModal();
      cancel.focus();
    });
})();
