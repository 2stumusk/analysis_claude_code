// Desk pet screen simulator. Draws exactly what the 320x240 device would show,
// from the same state JSON the device will receive.
(() => {
  "use strict";

  const W = 320, H = 240;
  const MONO = 'ui-monospace, "SF Mono", Menlo, Consolas, monospace';
  const SANS = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  const COLORS = {
    thinking: "#8ab4ff", reading: "#5fd4c4", editing: "#c79bff", running: "#ffd166",
    waiting: "#ff8a3d", done: "#7ee081", error: "#ff5d5d", idle: "#e8e6e3", offline: "#5a5f68",
  };
  const LABELS = {
    thinking: "THINKING", reading: "READING", editing: "EDITING", running: "RUNNING",
    waiting: "NEEDS YOU", done: "DONE", error: "ERROR", idle: "IDLE", offline: "OFFLINE",
  };
  const SHORT = {
    thinking: "THINK", reading: "READ", editing: "EDIT", running: "RUN",
    waiting: "WAIT", done: "DONE", error: "ERR", idle: "IDLE", offline: "OFF",
  };
  const VIEWS = ["face", "clock", "weather", "agents", "stats"];
  const BG = "#0b0d10", FG = "#e8e6e3", DIM = "#7a808a", FAINT = "#262a31";

  const canvas = document.getElementById("screen");
  const ctx = canvas.getContext("2d");
  let scale = 1;

  let snap = null;          // latest state from the daemon
  let connected = false;
  let view = "face";
  let preview = null;       // forced state for face preview
  let toast = null;         // {text, until}
  let soundOn = false;
  let audio = null;
  let lastAlertBeep = 0;
  let prev = { states: {}, alerts: {} };
  let approvalSeen = { id: null, at: 0 };  // when the current request first showed
  const ARM = 0.8;  // seconds before the buttons answer a new request (no accidental presses)
  const WAKE = 30;  // seconds a key press keeps the screen lit at night (as the firmware)
  let awakeUntil = 0;

  // ---------- helpers ----------
  const now = () => Date.now() / 1000;
  const pad = (n) => String(n).padStart(2, "0");
  const fmtDur = (s) => {
    s = Math.max(0, Math.floor(s));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${pad(m)}:${pad(s % 60)}`;
  };
  const fmtNum = (n) => n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "k" : String(n);
  const lerp = (a, b, t) => a + (b - a) * t;

  function fit(text, maxW) {
    if (ctx.measureText(text).width <= maxW) return text;
    while (text.length > 1 && ctx.measureText(text + "…").width > maxW) text = text.slice(0, -1);
    return text + "…";
  }

  function rrect(x, y, w, h, r) {
    r = Math.max(0, Math.min(r, w / 2, h / 2));
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function text(str, x, y, { size = 12, color = FG, font = SANS, weight = 400, align = "left" } = {}) {
    ctx.font = `${weight} ${size}px ${font}`;
    ctx.fillStyle = color;
    ctx.textAlign = align;
    ctx.textBaseline = "alphabetic";
    ctx.fillText(str, x, y);
  }

  const OFFLINE = { state: "offline", detail: "", tools: 0, sessions: 0, cwd: "", alert: false };

  function agentList() {
    return snap ? (snap.order || Object.keys(snap.agents)) : ["claude", "codex"];
  }

  function agentOf(name) {
    return (snap && snap.agents[name]) || OFFLINE;
  }

  // Screen names come from the daemon so new agents need no firmware change.
  function label(name) {
    const a = snap && snap.agents[name];
    return (a && a.label) || String(name || "").toUpperCase().slice(0, 8);
  }

  function abbr(name) {
    const a = snap && snap.agents[name];
    return (a && a.abbr) || String(name || "").toUpperCase().slice(0, 2);
  }

  function focusAgent() {
    const name = (snap && snap.focus) || agentList()[0] || null;
    return { name, a: agentOf(name) };
  }

  function faceState() {
    if (preview) return preview;
    return focusAgent().a.state;
  }

  // ---------- eyes ----------
  // Eye pose eases toward a target so expressions blend instead of snapping.
  const pose = { lx: 0, ly: 0, h: 1, lid: 0, sad: 0 };
  let look = { x: 0, y: 0, until: 0 };
  let blinkAt = now() + 3;

  function targetPose(state, t, mood) {
    const p = { lx: 0, ly: 0, h: 1, lid: 0, sad: 0 };
    switch (state) {
      case "idle":
        if (t > look.until) {
          look = { x: (Math.random() - 0.5) * 24, y: (Math.random() - 0.5) * 10, until: t + 2 + Math.random() * 3 };
        }
        p.lx = look.x; p.ly = look.y;
        if (mood === "hungry") { p.sad = 1; p.h = 0.8; p.ly = 6; }
        break;
      case "thinking": p.lx = 12; p.ly = -12; p.h = 0.92; break;
      case "reading": p.lx = Math.sin(t * 2.2) * 16; p.ly = 5; p.h = 0.78; break;
      case "editing": p.ly = 9; p.lid = 0.38; break;
      case "running": p.ly = Math.sin(t * 9) * 3; p.h = 1.02; break;
      case "waiting": p.h = 1.12; p.ly = -2; break;
      case "offline": p.h = 0.08; break;
    }
    return p;
  }

  function drawEyes(cx, cy, s, state, t, mood, color) {
    const tp = targetPose(state, t, mood);
    const k = 0.12;
    for (const key in pose) pose[key] = lerp(pose[key], tp[key], k);

    // blink
    let blink = 1;
    if (state !== "offline" && state !== "done" && state !== "error") {
      if (t > blinkAt + 0.16) blinkAt = t + 2.5 + Math.random() * 4;
      if (t > blinkAt) blink = Math.abs((t - blinkAt) / 0.08 - 1);
    }

    const ew = 58 * s, ehBase = 66 * s, gap = 42 * s, r = 18 * s;
    const eh = Math.max(4 * s, ehBase * pose.h * blink);
    ctx.fillStyle = color;
    ctx.strokeStyle = color;

    for (const side of [-1, 1]) {
      const ex = cx + side * (gap / 2 + ew / 2) + pose.lx * s - ew / 2;
      const ey = cy + pose.ly * s - eh / 2;

      if (state === "done") {
        // happy ^ ^
        ctx.lineWidth = 9 * s; ctx.lineCap = "round";
        ctx.beginPath();
        ctx.arc(ex + ew / 2, cy + 10 * s, ew * 0.38, Math.PI * 1.15, Math.PI * 1.85);
        ctx.stroke();
        continue;
      }
      if (state === "error") {
        ctx.lineWidth = 8 * s; ctx.lineCap = "round";
        const m = ew * 0.3, mx = ex + ew / 2, my = cy;
        ctx.beginPath();
        ctx.moveTo(mx - m, my - m); ctx.lineTo(mx + m, my + m);
        ctx.moveTo(mx + m, my - m); ctx.lineTo(mx - m, my + m);
        ctx.stroke();
        continue;
      }
      rrect(ex, ey, ew, eh, Math.min(r, eh / 2));
      ctx.fill();
      // eyelids: cut the top with the background colour
      if (pose.lid > 0.02 || pose.sad > 0.02) {
        ctx.fillStyle = BG;
        ctx.beginPath();
        const lidY = ey + eh * pose.lid;
        const tilt = pose.sad * 14 * s * side;  // sad: outer corners droop
        ctx.moveTo(ex - 4, ey - 4);
        ctx.lineTo(ex + ew + 4, ey - 4);
        ctx.lineTo(ex + ew + 4, lidY + Math.max(0, tilt));
        ctx.lineTo(ex - 4, lidY + Math.max(0, -tilt));
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = color;
      }
    }
  }

  // ---------- decorations ----------
  function bubbleDots(x, y, t, color) {
    for (let i = 0; i < 3; i++) {
      const a = 0.25 + 0.75 * Math.max(0, Math.sin(t * 4 - i * 0.7));
      ctx.globalAlpha = a;
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(x + i * 11, y, 3.5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function spinner(x, y, t, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 3; ctx.lineCap = "round";
    ctx.beginPath(); ctx.arc(x, y, 9, t * 6, t * 6 + Math.PI * 1.3); ctx.stroke();
  }

  function bang(x, y, t, color) {
    const s = 1 + 0.12 * Math.sin(t * 8);
    ctx.save(); ctx.translate(x, y); ctx.scale(s, s);
    rrect(-3, -16, 6, 20, 3); ctx.fillStyle = color; ctx.fill();
    ctx.beginPath(); ctx.arc(0, 11, 3.5, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }

  function sparkles(cx, cy, t, color) {
    const pts = [[-110, -48], [104, -54], [-96, 40], [112, 30], [0, -70]];
    pts.forEach(([dx, dy], i) => {
      const a = Math.max(0, Math.sin(t * 3 + i * 1.7));
      const r = 2 + a * 4;
      ctx.globalAlpha = a; ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(cx + dx, cy + dy - r * 1.6); ctx.lineTo(cx + dx + r * 0.4, cy + dy);
      ctx.lineTo(cx + dx, cy + dy + r * 1.6); ctx.lineTo(cx + dx - r * 0.4, cy + dy);
      ctx.closePath(); ctx.fill();
      ctx.beginPath();
      ctx.moveTo(cx + dx - r * 1.6, cy + dy); ctx.lineTo(cx + dx, cy + dy + r * 0.4);
      ctx.lineTo(cx + dx + r * 1.6, cy + dy); ctx.lineTo(cx + dx, cy + dy - r * 0.4);
      ctx.closePath(); ctx.fill();
    });
    ctx.globalAlpha = 1;
  }

  function zzz(x, y, t) {
    for (let i = 0; i < 3; i++) {
      const p = (t * 0.5 + i / 3) % 1;
      ctx.globalAlpha = 1 - p;
      text("z", x + p * 18 + i * 4, y - p * 34, { size: 10 + i * 3, color: DIM, weight: 700 });
    }
    ctx.globalAlpha = 1;
  }

  function heart(x, y, s, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y + 4 * s);
    ctx.bezierCurveTo(x - 8 * s, y - 2 * s, x - 4 * s, y - 9 * s, x, y - 4 * s);
    ctx.bezierCurveTo(x + 4 * s, y - 9 * s, x + 8 * s, y - 2 * s, x, y + 4 * s);
    ctx.fill();
  }

  function hearts(cx, cy, t, since) {
    const p = (t - since) / 2.5;
    if (p < 0 || p > 1) return;
    ctx.globalAlpha = 1 - p;
    [-70, 0, 70].forEach((dx, i) => heart(cx + dx, cy - 30 - p * 40 - i * 6, 1.6, "#ff6b8b"));
    ctx.globalAlpha = 1;
  }

  function sweat(x, y, t) {
    const p = (t * 0.8) % 1;
    ctx.globalAlpha = 1 - p * 0.6;
    ctx.fillStyle = "#7cc4ff";
    ctx.beginPath();
    ctx.moveTo(x, y + p * 10 - 6);
    ctx.quadraticCurveTo(x + 5, y + p * 10 + 2, x, y + p * 10 + 4);
    ctx.quadraticCurveTo(x - 5, y + p * 10 + 2, x, y + p * 10 - 6);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  function face(cx, cy, s, state, t, mood) {
    const color = state === "idle" || state === "offline" ? (state === "offline" ? COLORS.offline : FG) : COLORS[state];
    drawEyes(cx, cy, s, state, t, mood, color);
    if (s < 0.8) return;
    extras(cx, cy, state, t, color, true);
  }

  // Thought dots, spinner, "!", sparkles, sweat, zzz: around the eyes or the cat.
  function extras(cx, cy, state, t, color, cursor) {
    if (state === "thinking") bubbleDots(cx + 78, cy - 58, t, color);
    if (state === "running") spinner(cx + 112, cy - 50, t, color);
    if (state === "waiting") bang(cx + 112, cy - 46, t, color);
    if (state === "done") sparkles(cx, cy, t, color);
    if (state === "error") sweat(cx + 104, cy - 40, t);
    if (state === "offline") zzz(cx + 92, cy - 30, t);
    if (state === "editing" && cursor) {
      if (Math.floor(t * 2) % 2) { ctx.fillStyle = color; ctx.fillRect(cx - 14, cy + 46, 28, 4); }
    }
  }

  // ---------- chrome ----------
  function topBar(t) {
    const d = new Date();
    text(`${pad(d.getHours())}:${pad(d.getMinutes())}`, 10, 18, { size: 14, weight: 700, font: MONO });
    const all = agentList();
    const short = all.length > 2;  // full names fit for two agents, abbreviations beyond
    const tags = all.map((name) => short ? abbr(name) : label(name));
    // Shrink type and spacing until every agent fits right of the clock.
    const room = W - 8 - 62;
    let size = 10, gap = short ? 18 : 22;
    const widthAt = (sz, g) => {
      ctx.font = `600 ${sz}px ${SANS}`;
      return tags.reduce((sum, tag) => sum + ctx.measureText(tag).width + g, 0);
    };
    while (widthAt(size, gap) > room && size > 8) { size -= 1; gap -= 3; }
    let x = W - 8;
    for (let i = all.length - 1; i >= 0; i--) {
      const a = agentOf(all[i]);
      ctx.font = `600 ${size}px ${SANS}`;
      const w = ctx.measureText(tags[i]).width;
      text(tags[i], x, 17, { size, weight: 600, color: a.state === "offline" ? DIM : FG, align: "right" });
      const pulse = a.alert ? 0.5 + 0.5 * Math.sin(t * 8) : 1;
      ctx.globalAlpha = pulse;
      ctx.fillStyle = COLORS[a.state];
      ctx.beginPath(); ctx.arc(x - w - 7, 13, size > 9 ? 4 : 3.5, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
      x -= w + gap;
    }
    if (!connected) text("NO DAEMON", 10, 34, { size: 9, color: COLORS.error, weight: 700 });
  }

  function alertRing(t) {
    if (!snap) return;
    const alert = Object.values(snap.agents).some((a) => a.alert);
    if (!alert && faceState() !== "waiting") return;
    const a = alert ? 0.45 + 0.45 * Math.sin(t * 6) : 0.25;
    ctx.strokeStyle = COLORS.waiting; ctx.globalAlpha = a; ctx.lineWidth = 4;
    rrect(2, 2, W - 4, H - 4, 10); ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function drawToast(t) {
    if (!toast || t > toast.until) return;
    ctx.font = `600 12px ${SANS}`;
    const w = ctx.measureText(toast.text).width + 24;
    rrect(W / 2 - w / 2, 34, w, 24, 12); ctx.fillStyle = "#2b3038"; ctx.fill();
    text(toast.text, W / 2, 50, { size: 12, weight: 600, align: "center" });
  }

  function bar(x, y, w, h, frac, color) {
    rrect(x, y, w, h, h / 2); ctx.fillStyle = FAINT; ctx.fill();
    if (frac > 0) { rrect(x, y, Math.max(h, w * Math.min(1, frac)), h, h / 2); ctx.fillStyle = color; ctx.fill(); }
  }

  // ---------- views ----------
  // ---------- cat skin (mirrors viewCat in firmware/src/ui.cpp) ----------
  const STATE_ZH = { offline: "离线", idle: "空闲", thinking: "思考中", reading: "读文件", editing: "改代码",
    running: "跑命令", waiting: "需要你", done: "完成啦", error: "出错了" };
  let catBlinkAt = now() + 3;
  function catFrame(st, hungry, t) {
    const two = (base, hz) => `${base}_${Math.floor(t * hz) & 1}`;
    if (t > catBlinkAt + 0.16) catBlinkAt = t + 2.5 + Math.random() * 4;
    const blinking = t > catBlinkAt;
    switch (st) {
      case "thinking": return blinking ? "blink" : two("think", 1);
      case "reading": return two("read", 1.5);
      case "editing": return two("type", 4);
      case "running": return two("type", 6);
      case "waiting": return two("wait", 3);
      case "done": return two("done", 2);
      case "error": return two("error", 4);
      case "offline": return two("sleep", 0.8);
      default: return hungry ? two("hungry", 1) : blinking ? "blink" : two("idle", 0.7);
    }
  }
  function drawCat(name, x0, y0, scale) {
    const art = window.CAT_ART;
    if (!art) return;
    art.frames[name].forEach((row, y) => {
      for (let x = 0; x < art.size;) {
        let run = 1;
        while (x + run < art.size && row[x + run] === row[x]) run++;
        const color = art.palette[parseInt(row[x], 16)];
        if (color) { ctx.fillStyle = color; ctx.fillRect(x0 + x * scale, y0 + y * scale, run * scale, scale); }
        x += run;
      }
    });
  }
  function viewCat(t) {
    const st = faceState();
    const hungry = st === "idle" && snap && snap.pet.mood === "hungry" && !preview;
    drawCat(catFrame(st, hungry, t), 96, 32, 4);
    extras(W / 2, 100, st, t, st === "idle" ? FG : COLORS[st], false);
    if (snap) {
      hearts(W / 2, 100, t, snap.pet.fed_at ? Math.max(snap.pet.fed_at, snap.pet.levelup_at || 0) : snap.pet.levelup_at || -1);
    }
    topBar(t);

    const { name, a } = focusAgent();
    const color = COLORS[st];
    rrect(10, 166, W - 20, 60, 10); ctx.fillStyle = "#15181d"; ctx.fill();
    circle(24, 180, 4, color);
    const rot = !preview && snap && snap.rotation;
    const who = name ? label(name) : "DESK PET";
    text(rot && rot.count > 1 ? `${who}  ${rot.index + 1}/${rot.count}` : who, 34, 186, { size: 13, weight: 800 });
    const zh = hungry ? "饿了" : STATE_ZH[st];
    ctx.font = `600 11px ${SANS}`;
    const tw = ctx.measureText(zh).width;
    ctx.globalAlpha = 0.25; rrect(W - 22 - tw - 16, 172, tw + 16, 19, 9); ctx.fillStyle = color; ctx.fill();
    ctx.globalAlpha = 1;
    text(zh, W - 22 - tw / 2 - 8, 186, { size: 11, weight: 600, color, align: "center" });

    let detail = preview ? "preview" : a.detail || "";
    if (!preview && st === "offline") detail = connected ? "还没有 Agent 在工作" : "电脑上运行 deskpet --serial auto";
    else if (!preview && st === "idle") detail = hungry ? "饿了，按 B 喂我" : a.cwd || "空闲中，随时开工";
    ctx.font = `400 12px ${MONO}`;
    text(fit(detail, W - 44), 22, 205, { size: 12, font: MONO, color: "#b9bec6" });

    // Real numbers only: hooks report no "percent done", so the bar just shows activity.
    const stats = [];
    const busy = st !== "idle" && st !== "offline";
    if (!preview && a.task_start && busy) stats.push(`用时 ${fmtDur(now() - a.task_start)}`);
    if (!preview && a.tools && st !== "offline") stats.push(`工具 ${a.tools} 次`);
    const s = stats.join(" · ");
    ctx.font = `400 10px ${SANS}`;
    const sw = s ? ctx.measureText(s).width : 0;
    if (s) text(s, W - 22, 220, { size: 10, color: DIM, align: "right" });
    const bx = 22, bw = W - 44 - (sw ? sw + 10 : 0), by = 213;
    if (bw > 20) {
      rrect(bx, by, bw, 5, 2); ctx.fillStyle = FAINT; ctx.fill();
      ctx.fillStyle = color;
      if (st === "done" || st === "error") { rrect(bx, by, bw, 5, 2); ctx.fill(); }
      else if (st === "waiting") {
        ctx.globalAlpha = 0.5 + 0.5 * Math.sin(t * 6); rrect(bx, by, bw, 5, 2); ctx.fill(); ctx.globalAlpha = 1;
      } else if (busy) {
        const seg = bw / 3, pos = ((t * 90) % (bw + seg)) - seg;
        const x0 = Math.max(0, pos), x1 = Math.min(bw, pos + seg);
        if (x1 > x0) { rrect(bx + x0, by, x1 - x0, 5, 2); ctx.fill(); }
      }
    }
  }

  function viewFace(t) {
    if (snap && snap.skin === "cat") return viewCat(t);
    const st = faceState();
    const mood = snap ? snap.pet.mood : "ok";
    face(W / 2, 100, 1, st, t, mood);
    if (snap) {
      hearts(W / 2, 100, t, snap.pet.fed_at ? Math.max(snap.pet.fed_at, snap.pet.levelup_at || 0) : snap.pet.levelup_at || -1);
    }
    topBar(t);

    const { name, a } = focusAgent();
    const color = COLORS[st];
    const stateLabel = LABELS[st];
    const agentLabel = (st === "offline" && !preview) || !name ? "" : label(name);
    text(stateLabel, 12, 196, { size: 20, weight: 800, color });
    ctx.font = `800 20px ${SANS}`;
    const lw = ctx.measureText(stateLabel).width;
    const rot = !preview && snap && snap.rotation;
    const who = agentLabel && rot && rot.count > 1 ? `${agentLabel}  ${rot.index + 1}/${rot.count}` : agentLabel;
    if (who) text(who, 12 + lw + 8, 196, { size: 10, weight: 600, color: DIM });

    if (!preview && a.task_start && st !== "idle" && st !== "offline") {
      text(fmtDur(now() - a.task_start), W - 12, 196, { size: 14, weight: 700, font: MONO, align: "right", color: FG });
    }
    let detail = preview ? "preview" : a.detail || "";
    if (st === "offline" && !preview) detail = "waiting for an agent…";
    if (st === "idle" && !preview && snap) detail = snap.pet.mood === "hungry" ? "hungry · press B to feed" : "";
    ctx.font = `400 12px ${MONO}`;
    text(fit(detail, W - 24), 12, 214, { size: 12, font: MONO, color: "#b9bec6" });
    if (!preview && a.state !== "offline") {
      const bits = [];
      if (a.tools) bits.push(`${a.tools} tools`);
      if (a.cwd) bits.push(a.cwd);
      if (a.sessions > 1) bits.push(`${a.sessions} sessions`);
      ctx.font = `400 10px ${SANS}`;
      text(fit(bits.join(" · "), W - 24), 12, 231, { size: 10, color: DIM });
    }
  }

  function viewClock(t) {
    const d = new Date();
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    text(hm, W / 2 - 12, 104, { size: 68, weight: 700, font: MONO, align: "center" });
    text(pad(d.getSeconds()), W / 2 + 112, 104, { size: 20, weight: 700, font: MONO, color: DIM, align: "left" });
    const date = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
    text(date.toUpperCase(), W / 2, 132, { size: 13, weight: 600, color: DIM, align: "center" });

    const w = snap && snap.weather;
    if (connected && w && (w.status === "ok" || w.status === "stale")) {
      text(`${w.city}  ${w.temp}C  ${w.text}`, W / 2, 154, { size: 11, color: DIM, align: "center" });
    }

    // mini face + agent pills
    face(52, 190, 0.42, faceState(), t, snap ? snap.pet.mood : "ok");
    const names = agentList();
    if (names.length <= 3) {
      let y = 176;
      for (const name of names) {
        const a = agentOf(name);
        ctx.fillStyle = COLORS[a.state];
        ctx.beginPath(); ctx.arc(116, y - 4, 4, 0, Math.PI * 2); ctx.fill();
        text(label(name), 128, y, { size: 11, weight: 700 });
        text(LABELS[a.state], 202, y, { size: 11, weight: 700, color: COLORS[a.state] });
        if (a.task_start && a.state !== "idle" && a.state !== "offline") {
          text(fmtDur(now() - a.task_start), W - 12, y, { size: 11, font: MONO, color: DIM, align: "right" });
        }
        y += 22;
      }
    } else {
      // two columns of "● DS RUN" chips, up to four rows
      names.slice(0, 8).forEach((name, i) => {
        const a = agentOf(name);
        const x = 104 + (i % 2) * 106, y = 166 + Math.floor(i / 2) * 18;
        const pulse = a.alert ? 0.5 + 0.5 * Math.sin(t * 8) : 1;
        ctx.globalAlpha = pulse; ctx.fillStyle = COLORS[a.state];
        ctx.beginPath(); ctx.arc(x + 4, y - 4, 4, 0, Math.PI * 2); ctx.fill(); ctx.globalAlpha = 1;
        text(abbr(name), x + 14, y, { size: 11, weight: 800 });
        text(SHORT[a.state], x + 38, y, { size: 11, weight: 700, color: COLORS[a.state] });
      });
    }
    alertRing(t);
  }

  // The agent a short press of B acknowledges (same mark as the firmware).
  function focusMark(cy) {
    ctx.fillStyle = FG;
    ctx.beginPath(); ctx.moveTo(1, cy - 5); ctx.lineTo(6, cy); ctx.lineTo(1, cy + 5); ctx.closePath(); ctx.fill();
  }

  function viewAgents(t) {
    text("AGENTS", 12, 22, { size: 13, weight: 800, color: DIM });
    const names = agentList();
    if (!names.length) {
      text("no agent selected", W / 2, H / 2, { size: 12, color: DIM, align: "center" });
      return;
    }
    if (names.length > 3) return agentRows(t, names);
    const cardH = Math.min(96, (H - 36 - 8 * (names.length - 1)) / Math.max(1, names.length));
    names.forEach((name, i) => {
      const a = agentOf(name);
      const y = 32 + i * (cardH + 8);
      rrect(8, y, W - 16, cardH, 10); ctx.fillStyle = "#15181d"; ctx.fill();
      ctx.fillStyle = COLORS[a.state]; rrect(8, y, 5, cardH, 2.5); ctx.fill();
      if (snap && name === snap.focus) focusMark(y + cardH / 2);
      text(label(name), 22, y + 22, { size: 14, weight: 800 });
      text(LABELS[a.state], W - 20, y + 22, { size: 12, weight: 800, color: COLORS[a.state], align: "right" });
      ctx.font = `400 12px ${MONO}`;
      text(fit(a.detail || (a.state === "offline" ? "not connected" : a.state === "done" ? "task finished" : "—"), W - 44), 22, y + 44, { size: 12, font: MONO, color: "#b9bec6" });
      const bits = [];
      if (a.task_start && a.state !== "idle" && a.state !== "offline") bits.push(fmtDur(now() - a.task_start));
      if (a.tools) bits.push(`${a.tools} tools`);
      if (a.cwd) bits.push(a.cwd);
      if (a.sessions) bits.push(`${a.sessions} session${a.sessions > 1 ? "s" : ""}`);
      text(fit(bits.join(" · "), W - 44), 22, y + 64, { size: 11, color: DIM });
      if (a.alert) {
        ctx.strokeStyle = COLORS.waiting; ctx.globalAlpha = 0.5 + 0.5 * Math.sin(t * 6); ctx.lineWidth = 2;
        rrect(8, y, W - 16, cardH, 10); ctx.stroke(); ctx.globalAlpha = 1;
      }
    });
  }

  // Compact list for 4-8 agents: one row each.
  function agentRows(t, names) {
    const rowH = Math.min(26, (H - 40) / names.length);
    names.forEach((name, i) => {
      const a = agentOf(name);
      const y = 32 + i * rowH;
      if (i % 2 === 0) { ctx.fillStyle = "#12151a"; ctx.fillRect(6, y, W - 12, rowH); }
      if (a.alert) {
        ctx.globalAlpha = 0.35 + 0.35 * Math.sin(t * 6); ctx.fillStyle = COLORS.waiting;
        ctx.fillRect(6, y, W - 12, rowH); ctx.globalAlpha = 1;
      }
      const base = y + rowH / 2 + 4;
      ctx.fillStyle = COLORS[a.state];
      ctx.beginPath(); ctx.arc(16, base - 4, 4, 0, Math.PI * 2); ctx.fill();
      if (snap && name === snap.focus) focusMark(base - 4);
      text(label(name), 26, base, { size: 11, weight: 800, color: a.state === "offline" ? DIM : FG });
      text(SHORT[a.state], 100, base, { size: 11, weight: 800, color: COLORS[a.state] });
      const busy = a.task_start && a.state !== "idle" && a.state !== "offline";
      if (busy) text(fmtDur(now() - a.task_start), W - 12, base, { size: 10, font: MONO, color: DIM, align: "right" });
      ctx.font = `400 10px ${MONO}`;
      text(fit(a.detail || a.cwd || "", W - 150 - (busy ? 44 : 0)), 142, base, { size: 10, font: MONO, color: "#b9bec6" });
    });
  }

  function viewStats(t) {
    text("PET", 12, 22, { size: 13, weight: 800, color: DIM });
    const p = snap ? snap.pet : { level: 1, xp: 0, xp_level: 0, xp_next: 100, energy: 80, mood: "ok", tasks_today: 0, tools_today: 0, errors_today: 0 };
    face(56, 70, 0.5, p.mood === "hungry" ? "idle" : faceState(), t, p.mood);
    text(`LV ${p.level}`, 116, 52, { size: 22, weight: 800 });
    text(`${p.xp - p.xp_level} / ${p.xp_next - p.xp_level} XP`, W - 12, 52, { size: 11, font: MONO, color: DIM, align: "right" });
    bar(116, 60, W - 128, 8, (p.xp - p.xp_level) / Math.max(1, p.xp_next - p.xp_level), "#8ab4ff");
    const moodColor = p.mood === "happy" ? COLORS.done : p.mood === "ok" ? COLORS.running : COLORS.error;
    text(`ENERGY ${p.energy}`, 116, 88, { size: 11, weight: 700, color: DIM });
    text(p.mood.toUpperCase(), W - 12, 88, { size: 11, weight: 800, color: moodColor, align: "right" });
    bar(116, 94, W - 128, 8, p.energy / 100, moodColor);

    text("TODAY", 12, 132, { size: 13, weight: 800, color: DIM });
    const cells = [["TASKS", p.tasks_today], ["TOOLS", p.tools_today], ["ERRORS", p.errors_today]];
    const u = snap && snap.usage && snap.usage.claude;
    if (u) cells.push(["CLAUDE OUT", fmtNum(u.output)]);
    const cw = (W - 24) / cells.length;
    cells.forEach(([k, v], i) => {
      const x = 12 + i * cw;
      text(String(v), x, 162, { size: 20, weight: 800, font: MONO });
      text(k, x, 178, { size: 9, weight: 700, color: DIM });
    });
    if (u) {
      const total = u.input + u.output + u.cache_write;
      text(`claude tokens today ${fmtNum(total)} (+${fmtNum(u.cache_read)} cache read)`, 12, 206, { size: 11, color: DIM });
      text(`${u.messages} responses`, 12, 222, { size: 11, color: DIM });
    } else {
      text("usage reading off", 12, 206, { size: 11, color: DIM });
    }
  }

  // ---------- weather ----------
  const SUN = "#ffd166", MOON = "#e8e6e3", CLOUD = "#d7dbe0", CLOUD_DARK = "#8a929e", RAIN = "#7cc4ff";

  function circle(x, y, r, color) {
    ctx.fillStyle = color; ctx.beginPath(); ctx.arc(x, y, Math.max(0.5, r), 0, Math.PI * 2); ctx.fill();
  }

  function cloudShape(cx, cy, s, color) {
    circle(cx - 14 * s, cy + 4 * s, 12 * s, color);
    circle(cx + 2 * s, cy - 6 * s, 16 * s, color);
    circle(cx + 16 * s, cy + 4 * s, 11 * s, color);
    rrect(cx - 26 * s, cy + 2 * s, 53 * s, 14 * s, 7 * s); ctx.fillStyle = color; ctx.fill();
  }

  function sunShape(cx, cy, s, spin) {
    circle(cx, cy, 15 * s, SUN);
    if (s < 0.5) return;
    ctx.strokeStyle = SUN; ctx.lineWidth = 3.6 * s; ctx.lineCap = "round";
    for (let i = 0; i < 8; i++) {
      const a = spin + (i * Math.PI) / 4;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * 21 * s, cy + Math.sin(a) * 21 * s);
      ctx.lineTo(cx + Math.cos(a) * 28 * s, cy + Math.sin(a) * 28 * s);
      ctx.stroke();
    }
  }

  function moonShape(cx, cy, s) {
    circle(cx, cy, 15 * s, MOON);
    circle(cx + 8 * s, cy - 6 * s, 13 * s, BG);
  }

  // Same drawing as weatherIcon() in firmware/src/ui.cpp.
  function weatherIcon(cx, cy, s, sky, day, t) {
    const anim = s >= 0.8 ? t : 0;
    if (sky === "clear") {
      if (day) sunShape(cx, cy, s * 1.15, anim * 0.4); else moonShape(cx, cy, s * 1.2);
    } else if (sky === "partly") {
      if (day) sunShape(cx - 12 * s, cy - 10 * s, s * 0.75, anim * 0.4); else moonShape(cx - 12 * s, cy - 10 * s, s * 0.8);
      cloudShape(cx + 6 * s, cy + 6 * s, s * 0.85, CLOUD);
    } else if (sky === "fog") {
      for (let i = 0; i < 4; i++) {
        rrect(cx - 26 * s + (i % 2 ? 6 : -6) * s, cy + (-14 + i * 9) * s, 52 * s, 5 * s + 1, 2.5 * s);
        ctx.fillStyle = CLOUD; ctx.fill();
      }
    } else if (sky === "rain" || sky === "drizzle" || sky === "snow") {
      cloudShape(cx, cy - 8 * s, s, sky === "snow" ? CLOUD : CLOUD_DARK);
      const fall = s >= 0.8 ? (t * 1.2) % 1 : 0.4;
      for (let i = 0; i < 3; i++) {
        const x = cx + (-14 + i * 14) * s, y = cy + (16 + fall * 8 + (i % 2) * 5) * s;
        if (sky === "rain") {
          ctx.strokeStyle = RAIN; ctx.lineWidth = 3.2 * s + 0.8; ctx.lineCap = "round";
          ctx.beginPath(); ctx.moveTo(x + 3 * s, y - 5 * s); ctx.lineTo(x - 1 * s, y + 4 * s); ctx.stroke();
        } else {
          circle(x, y, (sky === "snow" ? 3 : 2) * s + 1, sky === "snow" ? "#ffffff" : RAIN);
        }
      }
    } else if (sky === "thunder") {
      cloudShape(cx, cy - 8 * s, s, CLOUD_DARK);
      ctx.fillStyle = SUN;
      ctx.beginPath();
      ctx.moveTo(cx + 2 * s, cy + 4 * s); ctx.lineTo(cx - 8 * s, cy + 20 * s); ctx.lineTo(cx + 1 * s, cy + 20 * s);
      ctx.closePath(); ctx.fill();
      ctx.beginPath();
      ctx.moveTo(cx - 1 * s, cy + 17 * s); ctx.lineTo(cx + 8 * s, cy + 17 * s); ctx.lineTo(cx - 4 * s, cy + 34 * s);
      ctx.closePath(); ctx.fill();
    } else {  // cloudy
      cloudShape(cx + 10 * s, cy - 8 * s, s * 0.7, CLOUD_DARK);
      cloudShape(cx - 2 * s, cy + 4 * s, s, CLOUD);
    }
  }

  function viewWeather(t) {
    const w = snap && snap.weather;
    const ready = connected && w && (w.status === "ok" || w.status === "stale");
    if (!ready) {
      weatherIcon(W / 2, 78, 1, "partly", true, t);
      const title = !connected ? "not connected" : !w ? "no city set" : w.status === "error" ? "weather unavailable" : "loading weather...";
      text(title, W / 2, 150, { size: 14, weight: 700, align: "center" });
      const sub = connected && !w ? "set a city in the panel →" : (w && w.query) || "";
      text(sub, W / 2, 172, { size: 11, color: DIM, align: "center" });
      return;
    }
    text(w.city, 12, 22, { size: 14, weight: 700 });
    const age = Math.floor((w.age || 0) / 60);
    const ageText = w.sample ? "sample data" : age < 1 ? "just updated" : `${w.status === "stale" ? "stale: " : ""}updated ${age} min ago`;
    text(ageText, W - 12, 21, { size: 11, color: w.status === "stale" ? COLORS.running : DIM, align: "right" });
    weatherIcon(70, 84, 1.25, w.kind, w.day, t);
    text(String(w.temp), 140, 104, { size: 60, weight: 400, font: SANS });
    ctx.font = `400 60px ${SANS}`;
    const tw = ctx.measureText(String(w.temp)).width;
    circle(140 + tw + 9, 58, 6, FG); circle(140 + tw + 9, 58, 3, BG);
    text("C", 140 + tw + 18, 72, { size: 16 });
    text(w.text, 140, 128, { size: 14, weight: 700 });
    if (w.hi != null && w.lo != null) text(`H ${w.hi}  L ${w.lo}`, 140, 148, { size: 11, color: DIM });
    text(`feels ${w.feels}  hum ${w.humidity}%  wind ${w.wind}` + (w.pop >= 0 ? `  rain ${w.pop}%` : ""), 12, 170, { size: 11, color: DIM });
    const colW = (W - 20) / 6;
    (w.hours || []).slice(0, 6).forEach((h, i) => {
      const x = 10 + colW * i + colW / 2;
      text(`${pad(h.h)}:00`, x, 190, { size: 9, color: DIM, align: "center" });
      weatherIcon(x, 204, 0.32, h.k, h.d, t);
      text(String(h.t), x, 228, { size: 11, align: "center" });
    });
  }

  // ---------- permission request ----------
  function approval() {
    return snap && snap.approval && !preview ? snap.approval : null;
  }
  function armed(t) {
    return approval() && t - approvalSeen.at >= ARM;
  }
  function wrapMono(str, maxW, maxLines) {
    ctx.font = `400 12px ${MONO}`;
    const lines = [];
    let rest = str;
    while (rest && lines.length < maxLines) {
      let n = rest.length;
      while (n > 1 && ctx.measureText(rest.slice(0, n)).width > maxW) n--;
      lines.push(rest.slice(0, n));
      rest = rest.slice(n);
    }
    if (rest && lines.length) lines[lines.length - 1] = lines[lines.length - 1].slice(0, -3) + "...";
    return lines;
  }
  // Mirrors the firmware: request on top, a countdown, and what A / B / C do.
  function viewApproval(t) {
    const ap = approval();
    const left = Math.max(0, ap.deadline - t);
    const total = Math.max(1, ap.wait || 30);
    const pulse = 0.55 + 0.45 * Math.sin(t * 6);
    ctx.strokeStyle = COLORS.waiting; ctx.globalAlpha = pulse; ctx.lineWidth = 4;
    rrect(2, 2, W - 4, H - 4, 10); ctx.stroke(); ctx.globalAlpha = 1;
    text(`${ap.label} asks to use`, 14, 24, { size: 12, color: DIM, weight: 600 });
    text(`${Math.ceil(left)}s`, W - 14, 24, { size: 14, weight: 700, font: MONO, align: "right",
      color: left < 6 ? COLORS.error : FG });
    text(fit(ap.tool, W - 28), 14, 52, { size: 20, weight: 800, color: COLORS.waiting });
    rrect(12, 64, W - 24, 82, 8); ctx.fillStyle = "#15181d"; ctx.fill();
    wrapMono(ap.detail || "", W - 44, 5).forEach((line, i) =>
      text(line, 22, 84 + i * 15, { size: 12, font: MONO }));
    bar(12, 156, W - 24, 4, left / total, left < 6 ? COLORS.error : COLORS.waiting);
    const ready = armed(t);
    [["DENY", 64, COLORS.error], ["ALLOW", 160, COLORS.done], ["LATER", 256, DIM]].forEach(([word, x, color]) => {
      ctx.globalAlpha = ready ? 1 : 0.35;
      rrect(x - 40, 180, 80, 30, 15); ctx.fillStyle = color; ctx.fill();
      text(word, x, 200, { size: 13, weight: 800, color: BG, align: "center" });
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.moveTo(x - 6, 220); ctx.lineTo(x + 6, 220); ctx.lineTo(x, 228); ctx.fill();
      ctx.globalAlpha = 1;
    });
  }
  function answer(decision) {
    const ap = approval();
    const word = { allow: "allowed", deny: "denied", skip: "on computer" }[decision];
    post("api/approval", { id: ap.id, decision }).then((r) => {
      toast = { text: r.ok ? `${word}: ${ap.label}` : "already answered", until: now() + 1.6 };
    }).catch(() => { toast = { text: "no daemon", until: now() + 1.4 }; });
  }

  // ---------- night mode ----------
  // 0 day, 1 dim, 2 off; alerts and permission requests keep the screen lit.
  function brightness(t) {
    const level = (snap && snap.night) || 0;
    if (!level || !connected || t < awakeUntil || preview) return 1;
    if (approval() || Object.values(snap.agents).some((a) => a.alert)) return 1;
    return level === 1 ? 0.12 : 0;
  }

  function enabledViews() {
    const pages = snap && snap.pages ? VIEWS.filter((v) => snap.pages.includes(v)) : VIEWS;
    return pages.length ? pages : VIEWS;
  }

  const DRAW = { face: viewFace, clock: viewClock, weather: viewWeather, agents: viewAgents, stats: viewStats };

  function frame() {
    const t = now();
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    ctx.fillStyle = BG; ctx.fillRect(0, 0, W, H);
    const pages = enabledViews();
    if (!pages.includes(view)) view = pages[0];
    const light = brightness(t);
    if (light === 0) {  // screen off: nothing drawn, like the device
      updateLed(t);
      requestAnimationFrame(frame);
      return;
    }
    if (approval()) {
      viewApproval(t);
      drawToast(t); updateLed(t); maybeBeep(t); dimScreen(light);
      requestAnimationFrame(frame);
      return;
    }
    DRAW[view](t);
    if (view === "face") alertRing(t);
    // one dot per enabled page
    pages.forEach((p, i) => {
      ctx.fillStyle = p === view ? FG : FAINT;
      ctx.beginPath(); ctx.arc(W / 2 - (pages.length - 1) * 6 + i * 12, H - 4, 2, 0, Math.PI * 2); ctx.fill();
    });
    drawToast(t);
    updateLed(t);
    maybeBeep(t);
    dimScreen(light);
    requestAnimationFrame(frame);
  }

  function dimScreen(light) {
    if (light >= 1) return;
    ctx.fillStyle = `rgba(0, 0, 0, ${1 - light})`;
    ctx.fillRect(0, 0, W, H);
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    scale = Math.max(1, Math.round((rect.width / W) * (window.devicePixelRatio || 1)));
    canvas.width = W * scale;
    canvas.height = H * scale;
  }

  // ---------- LED + sound ----------
  const led = document.getElementById("led");
  function updateLed(t) {
    if (!snap) { led.classList.remove("on"); return; }
    const alert = Object.values(snap.agents).some((a) => a.alert);
    const st = faceState();
    const on = alert ? Math.sin(t * 6) > 0 : st === "done" || st === "error";
    led.style.setProperty("--led", alert ? COLORS.waiting : COLORS[st]);
    led.classList.toggle("on", on);
  }

  function tone(freq, start, dur, type = "sine", gain = 0.08) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.type = type; o.frequency.value = freq;
    g.gain.setValueAtTime(0, audio.currentTime + start);
    g.gain.linearRampToValueAtTime(gain, audio.currentTime + start + 0.01);
    g.gain.exponentialRampToValueAtTime(0.0001, audio.currentTime + start + dur);
    o.connect(g).connect(audio.destination);
    o.start(audio.currentTime + start); o.stop(audio.currentTime + start + dur + 0.05);
  }
  const SOUNDS = {
    waiting: () => { tone(880, 0, 0.14); tone(660, 0.18, 0.2); },
    done: () => { tone(660, 0, 0.1); tone(880, 0.1, 0.1); tone(1320, 0.2, 0.22); },
    error: () => { tone(220, 0, 0.3, "square", 0.04); },
  };
  function play(name) {
    if (snap && snap.night && name !== "waiting") return;  // quiet at night, as the device
    if (soundOn && audio && SOUNDS[name]) SOUNDS[name]();
  }

  function maybeBeep(t) {
    if (!snap) return;
    const alert = Object.values(snap.agents).some((a) => a.alert);
    if (alert && t - lastAlertBeep > 8) { lastAlertBeep = t; play("waiting"); }
    if (!alert) lastAlertBeep = 0;
  }

  // React to transitions in new snapshots: jump to the face and chime.
  // Any agent finishing counts, even when another busy agent holds the face.
  function onTransitions(next) {
    const apId = next.approval ? next.approval.id : null;
    if (apId !== approvalSeen.id) {
      approvalSeen = { id: apId, at: now() };
      if (apId) play("waiting");
    }
    let jump = false;
    for (const [name, a] of Object.entries(next.agents)) {
      if (a.alert && !prev.alerts[name]) jump = true;
      if (a.state !== prev.states[name] && (a.state === "done" || a.state === "error")) {
        play(a.state);
        if (next.focus === name) jump = true;
      }
      prev.alerts[name] = a.alert;
      prev.states[name] = a.state;
    }
    if (jump && !preview) {
      const pages = enabledViews();
      if (pages.includes("face")) view = "face";
      else if (pages.includes("agents")) view = "agents";
    }
  }

  // ---------- data ----------
  const connEl = document.getElementById("conn");
  function setConn(ok) {
    connected = ok;
    connEl.className = "conn " + (ok ? "ok" : "bad");
    if (!ok) { connEl.textContent = "未连接守护进程：请运行 python -m deskpet"; return; }
    const dev = snap && snap.device;
    connEl.textContent = `已连接守护进程 ${location.host}` +
      (dev ? ` · USB 设备 ${dev.board || "未知板子"}（${dev.port}）` : "");
  }

  function apply(next) {
    onTransitions(next);
    snap = next;
    renderPanel();
    if (connected) setConn(true);
  }

  function connect() {
    if (!("EventSource" in window)) return poll();
    const es = new EventSource("api/stream");
    es.onmessage = (e) => { setConn(true); apply(JSON.parse(e.data)); };
    es.onerror = () => setConn(false);
  }

  async function poll() {
    try {
      const r = await fetch("api/state", { cache: "no-store" });
      apply(await r.json()); setConn(true);
    } catch { setConn(false); }
    setTimeout(poll, 1000);
  }

  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    return r.json();
  }

  // ---------- controls ----------
  function press(btn, el, all = false) {
    el.classList.add("pressed"); setTimeout(() => el.classList.remove("pressed"), 120);
    ensureAudio();
    const t = now(), dark = brightness(t) === 0;
    if (snap && snap.night) awakeUntil = t + WAKE;
    if (dark) return;  // this press only woke the screen
    if (approval()) {
      // While a request is on screen the keys answer it; long B does nothing.
      if (armed(now()) && !all) answer({ A: "deny", B: "allow", C: "skip" }[btn]);
      return;
    }
    if (btn === "C") { toggleSound(); return; }
    if (btn === "A") {
      const pages = enabledViews();
      view = pages[(pages.indexOf(view) + 1) % pages.length];
      return;
    }
    // Short press: the agent on screen; long press (or Shift+B): every agent.
    const focus = snap && snap.focus;
    const body = all ? { button: "B", all: true } : { button: "B", agent: focus || undefined };
    post("api/button", body).then((r) => {
      const texts = { ack: `OK: ${label(focus)}`, ack_all: "all clear", feed: "yum! +energy" };
      toast = { text: texts[r.action] || "ok", until: now() + 1.4 };
    }).catch(() => { toast = { text: "no daemon", until: now() + 1.4 }; });
  }

  function ensureAudio() {
    if (!audio && (window.AudioContext || window.webkitAudioContext)) {
      audio = new (window.AudioContext || window.webkitAudioContext)();
    }
  }

  const btnA = document.getElementById("btnA"), btnB = document.getElementById("btnB");
  const btnC = document.getElementById("btnC");
  btnA.addEventListener("click", () => press("A", btnA));
  btnC.addEventListener("click", () => press("C", btnC));
  // B: a press shorter than 0.8 s acknowledges the agent on screen, a longer one all of them.
  let bDown = 0;
  btnB.addEventListener("pointerdown", () => { bDown = performance.now(); });
  btnB.addEventListener("pointerup", () => {
    if (!bDown) return;
    const long = performance.now() - bDown >= 800;
    bDown = 0;
    press("B", btnB, long);
  });
  btnB.addEventListener("pointerleave", () => { bDown = 0; });
  btnB.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " " || e.key === "b" || e.key === "B") {
      e.preventDefault(); press("B", btnB, e.shiftKey);
    } else if (e.key === "a" || e.key === "A") press("A", btnA);
  });
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input:not([type=checkbox]), textarea, select") || e.target === btnB) return;
    if (e.key === "a" || e.key === "A") press("A", btnA);
    if (e.key === "b" || e.key === "B") press("B", btnB, e.shiftKey);
    if (e.key === "c" || e.key === "C") press("C", btnC);
  });

  document.getElementById("demo").addEventListener("click", () => {
    ensureAudio(); preview = null; renderChips(); view = "face";
    post("api/demo", {}).catch(() => setConn(false));
  });
  const soundBtn = document.getElementById("sound");
  soundBtn.addEventListener("click", () => { ensureAudio(); toggleSound(); });
  function toggleSound() {
    soundOn = !soundOn;
    soundBtn.textContent = "声音：" + (soundOn ? "开" : "关");
    soundBtn.setAttribute("aria-pressed", String(soundOn));
    if (soundOn) play("done");
    toast = { text: soundOn ? "sound on" : "muted", until: now() + 1.2 };
  }

  const chipsEl = document.getElementById("preview");
  function renderChips() {
    chipsEl.innerHTML = "";
    for (const st of [null, ...Object.keys(LABELS)]) {
      const b = document.createElement("button");
      b.className = "chip" + (preview === st ? " active" : "");
      b.textContent = st ? LABELS[st].toLowerCase() : "实时";
      b.addEventListener("click", () => { preview = st; view = "face"; renderChips(); });
      chipsEl.appendChild(b);
    }
  }

  const agentsEl = document.getElementById("agents"), rawEl = document.getElementById("raw");
  function renderPanel() {
    agentsEl.innerHTML = "";
    for (const name of agentList()) {
      const a = agentOf(name);
      const row = document.createElement("div");
      row.className = "agent";
      const dot = document.createElement("span"); dot.className = "dot"; dot.style.background = COLORS[a.state];
      const nm = document.createElement("span"); nm.className = "name"; nm.textContent = label(name);
      const st = document.createElement("span"); st.className = "state"; st.textContent = LABELS[a.state];
      const dt = document.createElement("span"); dt.className = "detail";
      dt.textContent = [a.detail, a.cwd, a.sessions ? `${a.sessions} 个会话` : ""].filter(Boolean).join(" · ") || "—";
      row.append(dot, nm, st, dt);
      agentsEl.appendChild(row);
    }
    rawEl.textContent = JSON.stringify(snap, null, 2);
    renderWeatherNote();
  }

  // ---------- agent selection ----------
  const PRESET_NAMES = { duo: "Claude + Codex", global: "海外", china: "国产", all: "全部" };
  const STATUS = { tested: "已实测", docs: "按官方文档", community: "按第三方资料", unverified: "未核实" };
  let config = null, catalog = [];
  const pickEl = document.getElementById("pick"), presetsEl = document.getElementById("presets");
  const pickNote = document.getElementById("pickNote");
  const rotateBox = document.getElementById("rotate");
  rotateBox.addEventListener("change", () => saveConfig({ rotate: rotateBox.checked }));
  const approvalsBox = document.getElementById("approvals"), waitSel = document.getElementById("approvalWait");
  const approvalNote = document.getElementById("approvalNote");
  approvalsBox.addEventListener("change", () => saveConfig({ approvals: approvalsBox.checked }));
  waitSel.addEventListener("change", () => saveConfig({ approval_wait: Number(waitSel.value) }));
  const nightOn = document.getElementById("nightOn"), nightFrom = document.getElementById("nightFrom");
  const nightTo = document.getElementById("nightTo"), nightLevel = document.getElementById("nightLevel");
  const nightNote = document.getElementById("nightNote");
  const saveNight = () => saveConfig({ night: { on: nightOn.checked, from: nightFrom.value || "23:00",
    to: nightTo.value || "07:00", level: nightLevel.value } });
  [nightOn, nightFrom, nightTo, nightLevel].forEach((el) => el.addEventListener("change", saveNight));
  function renderNight() {
    const n = config.night || { on: false, from: "23:00", to: "07:00", level: "off" };
    nightOn.checked = n.on;
    nightFrom.value = n.from; nightTo.value = n.to; nightLevel.value = n.level;
    [nightFrom, nightTo, nightLevel].forEach((el) => { el.disabled = !n.on; });
    nightNote.textContent = n.on
      ? `每天 ${n.from}–${n.to} ${n.level === "off" ? "熄屏" : "调暗"}（按电脑的本地时间）。有 Agent 需要你或有权限请求时照样亮屏；按任意键亮 30 秒，熄屏时这一下只负责点亮。夜里只有"需要你"会响，完成提示音静音。`
      : "关闭：屏幕一直亮着。";
  }
  const skinBtns = document.querySelectorAll("[data-skin]");
  skinBtns.forEach((b) => b.addEventListener("click", () => saveConfig({ skin: b.dataset.skin })));
  function renderSkin() {
    skinBtns.forEach((b) => {
      const on = (config.skin || "cat") === b.dataset.skin;
      b.classList.toggle("active", on); b.setAttribute("aria-checked", String(on));
    });
  }
  function renderApprovals() {
    approvalsBox.checked = !!config.approvals;
    waitSel.value = String(config.approval_wait || 30);
    waitSel.disabled = !config.approvals;
    approvalNote.textContent = config.approvals
      ? "只在桌宠 USB 连着（或本页开着）时生效。限时内没按键、按 C、或设备断开，都会退回电脑上原来的确认框。" +
        "改过 hooks 的话要重新复制下方 Claude Code / Codex 的配置（PermissionRequest 超时改成了 90 秒），Codex 还要在 /hooks 里重新信任。"
      : "关闭时权限请求照常只在电脑上确认，桌宠只提醒。";
  }

  async function loadConfig() {
    try {
      [config, catalog] = await Promise.all([
        fetch("api/config", { cache: "no-store" }).then((r) => r.json()),
        fetch("api/agents", { cache: "no-store" }).then((r) => r.json()),
      ]);
      renderPicker(); renderPages(); renderSetup();
    } catch { /* daemon offline: the connection line already says so */ }
  }

  async function saveConfig(patch) {
    config = Object.assign(config, await post("api/config", patch));
    renderPicker();
    renderPages();
  }

  const PAGE_NAMES = { face: "表情", clock: "时钟", weather: "天气", agents: "Agent 列表", stats: "宠物" };
  const pagesEl = document.getElementById("pages"), cityInput = document.getElementById("city");
  const weatherNote = document.getElementById("weatherNote");

  function renderPages() {
    pagesEl.innerHTML = "";
    for (const page of config.all_pages || VIEWS) {
      const on = config.pages.includes(page);
      const b = document.createElement("button");
      b.className = "chip" + (on ? " on" : "");
      b.textContent = PAGE_NAMES[page] || page;
      b.setAttribute("aria-pressed", String(on));
      b.onclick = () => {
        const next = on ? config.pages.filter((p) => p !== page) : config.pages.concat(page);
        if (next.length) saveConfig({ pages: next });
      };
      pagesEl.appendChild(b);
    }
    if (document.activeElement !== cityInput) cityInput.value = config.city || "";
  }

  document.getElementById("cityForm").addEventListener("submit", (e) => {
    e.preventDefault();
    saveConfig({ city: cityInput.value.trim() });
    cityInput.blur();
  });

  function renderWeatherNote() {
    const w = snap && snap.weather;
    if (!w) {
      weatherNote.textContent = "未设置城市，天气页显示提示。数据来自 Open-Meteo，免费接口仅限非商业用途。";
      return;
    }
    const where = w.city ? `${w.query || w.city}（${w.city}）` : w.query;
    const states = { ok: w.sample ? "样例数据" : "已更新", stale: "数据过期，正在重试", loading: "正在获取", error: "获取失败" };
    weatherNote.textContent = `${where}：${states[w.status] || w.status}` +
      (w.text_zh ? ` · ${w.text_zh} ${w.temp}°C` : "") + (w.error ? ` · ${w.error}` : "") +
      " · 数据来自 Open-Meteo（免费接口仅限非商业用途）";
  }

  function renderPicker() {
    document.querySelectorAll(".seg-btn").forEach((b) => {
      const on = b.dataset.mode === config.mode;
      b.classList.toggle("active", on); b.setAttribute("aria-checked", String(on));
      b.onclick = () => saveConfig({ mode: b.dataset.mode });
    });
    const auto = config.mode === "auto";
    presetsEl.innerHTML = "";
    for (const [key, list] of Object.entries(config.presets || {})) {
      const b = document.createElement("button");
      b.textContent = PRESET_NAMES[key] || key; b.disabled = auto;
      b.onclick = () => saveConfig({ mode: "custom", agents: list });
      presetsEl.appendChild(b);
    }
    pickEl.innerHTML = "";
    for (const info of catalog) {
      const on = config.agents.includes(info.id);
      const b = document.createElement("button");
      b.className = "chip" + (on ? " on" : ""); b.disabled = auto;
      b.textContent = info.label; b.title = info.name;
      b.setAttribute("aria-pressed", String(on));
      b.onclick = () => {
        const next = on ? config.agents.filter((x) => x !== info.id) : config.agents.concat(info.id);
        if (next.length) saveConfig({ agents: next });
      };
      pickEl.appendChild(b);
    }
    rotateBox.checked = config.rotate !== false;
    renderApprovals();
    renderNight();
    renderSkin();
    pickNote.textContent = auto
      ? "自动模式：哪个 Agent 有活动会话就显示哪个，全部空闲时显示 OFFLINE。"
      : `已选 ${config.agents.length} 个。超过 2 个时顶栏用缩写，超过 3 个时列表页改为紧凑行。`;
  }

  function renderSetup() {
    const list = document.getElementById("setupList");
    list.innerHTML = "";
    for (const info of catalog) {
      const box = document.createElement("div"); box.className = "setup-item";
      const head = document.createElement("header");
      const name = document.createElement("b"); name.textContent = info.name;
      const badge = document.createElement("span"); badge.className = "badge " + info.status;
      badge.textContent = STATUS[info.status] || info.status;
      head.append(name, badge);
      const where = document.createElement("div");
      const cmd = document.createElement("code"); cmd.textContent = info.command;
      where.append(cmd, document.createTextNode(" → " + info.file));
      box.append(head, where);
      if (info.notes.length) {
        const ul = document.createElement("ul");
        for (const n of info.notes) { const li = document.createElement("li"); li.textContent = n; ul.appendChild(li); }
        box.appendChild(ul);
      }
      const pre = document.createElement("pre"); pre.textContent = info.text;
      box.appendChild(pre);
      list.appendChild(box);
    }
  }

  renderChips();
  loadConfig();
  resize();
  window.addEventListener("resize", resize);
  connect();
  requestAnimationFrame(frame);
})();
