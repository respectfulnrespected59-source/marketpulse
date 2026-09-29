/* MarketPulse Classes — the Classes tab.
 *
 * Lists every class and lesson from the public catalogue (/api/classes): which
 * lessons are free, which need the Classes pass ($19/mo, also in Pro+), and a
 * place to activate a pass key. Starting a lesson moves to the Live tab and
 * hands it to the player (lesson-player.js). The server decides access; the
 * locks here are just the honest picture of what it will say.
 *
 * Everything is built with textContent — catalogue text never becomes markup.
 */

let classesData = null;
let classesRenderSeq = 0;         // only the newest render may paint the tab
let classesPendingMsg = null;     // a message to show on the next render (see classesShowLocked)

function _cEl(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function _classesLocked(lesson) {
  return !lesson.free && !(classesData && classesData.access && classesData.access.entitled);
}

function _lessonRow(lesson, n) {
  const row = _cEl("button", "cls-lesson");
  row.type = "button";
  row.append(_cEl("span", "cls-num", String(n)), _cEl("span", "cls-name", lesson.title));
  const locked = _classesLocked(lesson);
  row.append(_cEl("span", "cls-badge " + (lesson.free ? "is-free" : locked ? "is-locked" : "is-open"),
                  lesson.free ? "FREE" : locked ? "PASS" : "▶"));
  row.setAttribute("aria-label", `${lesson.title}${lesson.free ? ", free" : locked ? ", needs the Classes pass" : ""}`);
  row.addEventListener("click", () => {
    if (_classesLocked(lesson)) return classesShowLocked(lesson.id);
    setView("live");
    lessonStart(lesson.id);
  });
  return row;
}

function _classCard(c) {
  const card = _cEl("div", "coach-card cls-card");
  card.append(_cEl("h3", null, c.title), _cEl("p", "cls-tag", c.tagline || ""));
  if (!c.lessons.length) { card.append(_cEl("p", "cls-soon", "Lessons coming soon.")); return card; }
  c.lessons.forEach((l, i) => card.append(_lessonRow(l, i + 1)));
  return card;
}

function _unlockedBox() {
  const box = _cEl("div", "coach-card cls-unlock");
  box.id = "classesUnlock";
  box.append(_cEl("h3", null, "Classes unlocked"),
             _cEl("p", null, classesData.access.tier === "proplus"
               ? "Included with your Pro+ license on this device."
               : "Your Classes pass is active on this device."));
  if (typeof mpClassesPass === "function" && mpClassesPass()) {
    const off = _cEl("button", "add-btn ghost", "Release this device");
    off.type = "button";
    off.addEventListener("click", async () => {
      off.disabled = true;
      let r;
      try { r = await mpClassesRelease(); } catch (e) { r = { message: "Could not reach MarketPulse. Try again." }; }
      if (r.ok) return renderClasses();
      off.disabled = false;
      box.append(_cEl("p", "lic-msg", r.message || "Could not release the seat."));
    });
    box.append(off);
  }
  return box;
}

function _keyForm(message) {
  const wrap = _cEl("div");
  const form = _cEl("form", "lic-row");
  const input = _cEl("input", "add-input lic-key");
  Object.assign(input, { type: "text", placeholder: "Paste your Classes pass key", autocomplete: "off",
                         spellcheck: false, maxLength: 64 });
  input.setAttribute("aria-label", "Classes pass key");
  const go = _cEl("button", "add-btn", "Activate");
  go.type = "submit";
  form.append(input, go);
  const msg = _cEl("p", "lic-msg", message || "");
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const key = input.value.trim();
    if (!key || typeof mpLicenseActivate !== "function") return;
    go.disabled = true;
    msg.textContent = "Checking with Gumroad…";
    try {
      const r = await mpLicenseActivate(key);
      if (r.ok) return renderClasses();
      msg.textContent = r.message || "That key could not be activated.";
    } catch (e) {
      msg.textContent = "Could not reach MarketPulse. Check your connection and try again.";
    } finally {
      go.disabled = false;
    }
  });
  wrap.append(form, msg);
  return wrap;
}

function _unlockBox(message) {
  if (classesData && classesData.access && classesData.access.entitled) return _unlockedBox();
  const box = _cEl("div", "coach-card cls-unlock");
  box.id = "classesUnlock";
  box.append(_cEl("h3", null, "Unlock every lesson"),
             _cEl("p", null, "Lesson 1 of every class is free. The Classes pass unlocks the rest: "
                                + "$19 a month, cancel any time. Pro+ includes it."));
  // https only: the link comes from server config and lands in a clickable href.
  if (classesData && typeof classesData.upgrade === "string" && /^https:\/\//.test(classesData.upgrade)) {
    const buy = _cEl("a", "add-btn cls-buy", "Get the Classes pass");
    Object.assign(buy, { href: classesData.upgrade, target: "_blank", rel: "noopener noreferrer" });
    box.append(buy);
  }
  box.append(_keyForm(message));
  return box;
}

/* The catalogue, asked with the Classes pass and then the main key: a lapsed pass
 * must not hide a Pro+ license that includes classes. */
async function _classesFetch() {
  const sets = typeof _lessonHeaderSets === "function" ? _lessonHeaderSets() : [{}];
  let data = null;
  for (const headers of sets) {
    const r = await fetch("/api/classes", { headers });
    if (!r.ok) throw Object.assign(new Error(String(r.status)), { status: r.status });
    data = await r.json();
    if (data.access && data.access.entitled) break;
  }
  return data;
}

async function renderClasses(message) {
  const body = $("#classesBody");
  if (!body) return;
  const seq = ++classesRenderSeq;
  const msg = message || classesPendingMsg;
  classesPendingMsg = null;
  body.replaceChildren(_cEl("p", "cls-soon", "Loading classes…"));
  let data;
  try {
    data = await _classesFetch();
  } catch (e) {
    if (seq === classesRenderSeq) {
      body.replaceChildren(_cEl("p", "cls-soon", e.status === 429
        ? "You've opened a lot of lessons in the last hour. Take a breather and try again in a few minutes."
        : "Couldn't reach MarketPulse. Check your connection and try again."));
    }
    return;
  }
  if (seq !== classesRenderSeq) return;                  // a newer render owns the tab
  classesData = data;
  message = msg;
  const classes = classesData.classes || [];
  if (!classes.some((c) => c.lessons.length)) {
    body.replaceChildren(_cEl("p", "cls-soon", "Classes stream from the MarketPulse web app. "
                                               + "New lessons are on the way."));
    return;
  }
  body.replaceChildren(_unlockBox(message), ...classes.map(_classCard));
}

/* The server said 402 (or a locked row was tapped): show why and how to unlock. */
async function classesShowLocked(lessonId) {
  const all = classesData ? (classesData.classes || []).flatMap((c) => c.lessons) : [];
  const title = (all.find((l) => l.id === lessonId) || {}).title;
  classesPendingMsg = title ? `"${title}" is part of the Classes pass.` : "That lesson is part of the Classes pass.";
  // ONE render: setView renders the tab (picking up the message); if we're already here, render now.
  if (state.view !== "classes") setView("classes");
  else await renderClasses();
  const wait = () => new Promise((r) => setTimeout(r, 50));
  for (let i = 0; i < 40 && !$("#classesUnlock"); i++) await wait();
  const u = $("#classesUnlock");
  if (u) u.scrollIntoView({ behavior: "smooth", block: "center" });
}
