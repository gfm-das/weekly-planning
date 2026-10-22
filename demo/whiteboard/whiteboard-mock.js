/*
 * whiteboard-mock.js: the demo's stand-in for portal-api's /api/whiteboards (and for the Presentations sign-in the live charts
 * use). FAKE data only: invented boards with sticky notes, shapes and text, made-up people. Reading works. Saves are kept in
 * this page's memory only (a reload brings the invented boards back), so nothing is ever stored or sent anywhere.
 * Loaded before the app's own scripts; it only replaces window.fetch for those two kinds of address.
 */
(() => {
  const NOTE = "This is a demo with fake data. Nothing is saved.";
  const now = Date.now();
  const iso = (hoursAgo) => new Date(now - hoursAgo * 3600e3).toISOString();

  // Theme as in demo-not-here.html: the portal's choice first (the shell then sends portal-theme messages).
  try {
    const t = (JSON.parse(localStorage.getItem("gfm_portal_layout_v1") || "null") || {}).theme || "mission";
    document.documentElement.dataset.theme = t;
  } catch (e) {}
  try { if (!localStorage.getItem("mission_access_token")) localStorage.setItem("mission_access_token", "demo"); } catch (e) {}

  // ---- Excalidraw elements (restoreElements fills in what is left out) ----
  let n = 0;
  const base = (type, x, y, w, h, extra) => ({
    id: "demo-" + type + "-" + ++n, type, x, y, width: w, height: h, angle: 0,
    strokeColor: "#1e1e1e", backgroundColor: "transparent", fillStyle: "solid", strokeWidth: 2, strokeStyle: "solid",
    roughness: 1, opacity: 100, groupIds: [], frameId: null, roundness: null, seed: 1000 + n, version: 1, versionNonce: 2000 + n,
    isDeleted: false, boundElements: null, updated: now, link: null, locked: false, ...extra,
  });
  const text = (x, y, value, size = 20, extra) => base("text", x, y, Math.max(...value.split("\n").map((l) => l.length)) * size * 0.55, size * 1.25 * value.split("\n").length, {
    text: value, originalText: value, fontSize: size, fontFamily: 5, textAlign: "left", verticalAlign: "top", containerId: null,
    lineHeight: 1.25, autoResize: true, ...extra,
  });
  const wrap = (value, max) => value.split(" ").reduce((out, word) => { const last = out[out.length - 1]; if (last !== undefined && (last + " " + word).length <= max) out[out.length - 1] = last + " " + word; else out.push(word); return out; }, []).join(String.fromCharCode(10));
  // A sticky note: a coloured rectangle with its text inside (a bound text element).
  const note = (x, y, value, color) => {
    const box = base("rectangle", x, y, 200, 140, { backgroundColor: color, strokeColor: "#9a8c3a", roundness: { type: 3 } });
    const lines = wrap(value, 16);
    const label = text(x + 10, y + 70 - lines.split(String.fromCharCode(10)).length * 11, lines, 18, { containerId: box.id, textAlign: "center", verticalAlign: "middle", width: 180, height: lines.split(String.fromCharCode(10)).length * 22.5 });
    box.boundElements = [{ type: "text", id: label.id }];
    return [box, label];
  };
  const shape = (type, x, y, w, h, color, value) => {
    const box = base(type, x, y, w, h, { backgroundColor: color, roundness: type === "rectangle" ? { type: 3 } : null });
    const label = text(x + 10, y + h / 2 - 12, value, 20, { containerId: box.id, textAlign: "center", verticalAlign: "middle", width: w - 20, height: 25 });
    box.boundElements = [{ type: "text", id: label.id }];
    return [box, label];
  };
  const arrow = (x, y, dx, dy) => base("arrow", x, y, Math.abs(dx), Math.abs(dy), {
    points: [[0, 0], [dx, dy]], startBinding: null, endBinding: null, startArrowhead: null, endArrowhead: "arrow", roundness: { type: 2 },
  });

  const BOARDS = [
    { id: "00000000-0000-4000-8000-000000000001", name: "Zone council: next steps", version: 3, created_at: iso(300), created_by_name: "Elder Sample",
      updated_at: iso(5), updated_by_name: "Sister Demo", pictures: 0,
      elements: () => [
        text(60, 30, "Zone council: next steps", 32),
        ...note(60, 110, "Share one invitation each day", "#ffec99"),
        ...note(290, 110, "Visit the less-active list", "#b2f2bb"),
        ...note(520, 110, "Practice the new teaching plan", "#a5d8ff"),
        ...note(175, 290, "Report numbers on Sunday", "#ffc9c9"),
        ...shape("ellipse", 440, 300, 240, 110, "#d0bfff", "Goal: 6 key indicators"),
        arrow(400, 355, 40, 0),
        text(60, 470, "Owner: Elder Sample\nReview: Sister Demo", 18),
      ] },
    { id: "00000000-0000-4000-8000-000000000002", name: "Training outline", version: 1, created_at: iso(120), created_by_name: "Sister Demo",
      updated_at: iso(50), updated_by_name: "Sister Demo", pictures: 0,
      elements: () => [
        text(60, 30, "Training outline", 32),
        ...shape("rectangle", 60, 110, 200, 80, "#a5d8ff", "1. Welcome"),
        ...shape("rectangle", 340, 110, 200, 80, "#b2f2bb", "2. Practice"),
        ...shape("rectangle", 620, 110, 200, 80, "#ffec99", "3. Commit"),
        arrow(262, 150, 76, 0),
        arrow(542, 150, 76, 0),
        ...note(340, 250, "Role play in pairs", "#ffc9c9"),
      ] },
    { id: "00000000-0000-4000-8000-000000000003", name: "Area plan (sample)", version: 2, created_at: iso(500), created_by_name: "Elder Sample",
      updated_at: iso(200), updated_by_name: "Elder Sample", pictures: 0,
      elements: () => [
        text(60, 30, "Area plan (sample)", 32),
        ...shape("diamond", 60, 110, 240, 150, "#ffec99", "Who needs help?"),
        ...note(380, 110, "Friends with a date", "#b2f2bb"),
        ...note(380, 290, "New members", "#a5d8ff"),
      ] },
  ];

  const boards = new Map(BOARDS.map((b) => [b.id, { ...b, scene: { type: "excalidraw", version: 2, elements: b.elements(), appState: {} } }]));
  const summary = (b) => { const { scene, elements, ...rest } = b; return rest; };
  const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
  const LIMITS = { name: 80, picture_bytes: 2097152, pictures: 60, pictures_bytes: 12582912, scene_bytes: 3145728 };
  let counter = 100;

  async function whiteboards(rest, method, body) {
    const id = rest.replace(/^\//, "");
    if (!id) {
      if (method === "GET") return json({ boards: [...boards.values()].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).map(summary), limits: LIMITS });
      if (method === "POST") {
        const name = String((body && body.name) || "").trim();
        if (!name) return json({ error: "Please give the board a name." }, 400);
        const source = body.copy_of && boards.get(body.copy_of);
        const stamp = new Date().toISOString();
        const fresh = { id: "00000000-0000-4000-8000-" + String(++counter).padStart(12, "0"), name, version: 1, created_at: stamp,
          created_by_name: "Elder Sample", updated_at: stamp, updated_by_name: "Elder Sample", pictures: 0,
          scene: source ? JSON.parse(JSON.stringify(source.scene)) : { type: "excalidraw", version: 2, elements: [], appState: {} } };
        boards.set(fresh.id, fresh);
        return json({ board: summary(fresh) }, 201);
      }
    }
    const board = boards.get(id);
    if (!board) return json({ error: "This board does not exist (any more)." }, 404);
    if (method === "GET") return json({ board: { ...summary(board), file_ids: [] }, scene: board.scene, files: {} });
    if (method === "PUT") {
      if (body && body.scene) board.scene = body.scene;
      board.version += 1; board.updated_at = new Date().toISOString(); board.updated_by_name = "Elder Sample";
      return json({ board: { ...summary(board), file_ids: [] } });
    }
    if (method === "PATCH") {
      const name = String((body && body.name) || "").trim();
      if (!name) return json({ error: "Please give the board a name." }, 400);
      board.name = name;
      return json({ board: summary(board) });
    }
    if (method === "DELETE") { boards.delete(id); return json({ ok: true }); }
    return json({ error: NOTE }, 405);
  }

  const realFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = typeof input === "string" ? input : input && input.url ? input.url : String(input);
    let url;
    try { url = new URL(raw, location.href); } catch (e) { return realFetch(input, init); }
    const method = String((init && init.method) || (input && input.method) || "GET").toUpperCase();
    if (url.pathname.endsWith("/api/session")) return json({ expires_at: new Date(Date.now() + 3600e3).toISOString() });
    const hit = /\/api\/whiteboards(\/[^/]*)?$/.exec(url.pathname);
    if (!hit) return realFetch(input, init);
    let body;
    try { body = init && init.body ? JSON.parse(init.body) : undefined; } catch (e) { body = undefined; }
    return whiteboards(hit[1] || "", method, body);
  };
  window.DEMO_WHITEBOARD_NOTE = NOTE;
})();
