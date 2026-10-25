"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const HEADER_W = 132;
const RULER_STEPS = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

function num(value, fallback = null) {
    if (value === "" || value === null || value === undefined) return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
}

function differs(a, b) {
    return Math.abs(Number(a) - Number(b)) > 0.0001;
}

function pad(value, size = 2) {
    return String(Math.floor(value)).padStart(size, "0");
}

function fmtTime(seconds, withMs = false) {
    const total = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
    const ms = total % 1000;
    const whole = Math.floor(total / 1000);
    const s = whole % 60;
    const m = Math.floor(whole / 60) % 60;
    const h = Math.floor(whole / 3600);
    const base = `${pad(h)}:${pad(m)}:${pad(s)}`;
    return withMs ? `${base}.${pad(ms, 3)}` : base;
}

function fmtShort(seconds) {
    const total = Math.max(0, Math.round(Number(seconds) || 0));
    const s = total % 60;
    const m = Math.floor(total / 60) % 60;
    const h = Math.floor(total / 3600);
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
}

function fmtRuler(seconds) {
    const total = Number(seconds) || 0;
    const whole = Math.floor(total);
    const m = Math.floor(whole / 60) % 60;
    const s = whole % 60;
    const h = Math.floor(whole / 3600);
    const frac = Math.round((total - Math.floor(total)) * 10);
    const suffix = frac ? `.${frac}` : "";
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}${suffix}` : `${pad(m)}:${pad(s)}${suffix}`;
}

function fmtBytes(bytes) {
    const value = Number(bytes) || 0;
    if (value > 1024 * 1024) return `${(value / (1024 * 1024)).toFixed(1)} MB`;
    if (value > 1024) return `${Math.round(value / 1024)} KB`;
    return `${value} B`;
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
}

function basename(path) {
    return String(path || "").split(/[\\/]/).pop() || "";
}

function isAudioPath(path) {
    return /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/i.test(String(path || ""));
}

function truncate(text, limit = 320) {
    const value = String(text ?? "");
    return value.length > limit ? `${value.slice(0, limit)}…` : value;
}

function mediaKind(path) {
    if (isAudioPath(path)) return "audio";
    if (/\.(mp4|mkv|webm|mov|avi|m4v)$/i.test(String(path || ""))) return "video";
    return "other";
}

const state = {
    projectId: null,
    project: null,
    projects: [],
    issues: [],
    history: { undo: [], redo: [] },
    versions: [],
    jobs: [],
    skills: [],
    uploads: [],
    selectedClipId: null,
    selectedSourcePath: null,
    playhead: 0,
    pps: 80,
    snap: true,
    monitor: "program",
    programLabel: "",
    sourceLabel: "",
    drag: null,
    markIn: null,
    markOut: null,
    analysis: null,
    analyzing: false,
    analysisKind: "scenes",
    mutationDepth: 0,
    refreshTimer: null,
    pollTimer: null,
    ws: null,
    virtualRaf: null,
    chatBusy: false,
    turnId: null,
    turnProjectId: null,
    answerShown: false,
    aiConnected: null,
    openQcJobId: null,
};

async function api(url, options = {}) {
    const opts = { ...options };
    if (opts.body !== undefined && typeof opts.body !== "string" && !(opts.body instanceof FormData)) {
        opts.headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
        opts.body = JSON.stringify(opts.body);
    }
    const response = await fetch(url, opts);
    const text = await response.text();
    let data = null;
    try {
        data = text ? JSON.parse(text) : null;
    } catch {
        data = text;
    }
    if (!response.ok) {
        const detail = data && typeof data === "object" && data.detail
            ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))
            : (typeof data === "string" && data ? data : `HTTP ${response.status}`);
        throw new Error(detail);
    }
    return data;
}

function toast(message, kind = "info") {
    const area = $("#toast-area");
    const item = document.createElement("div");
    item.className = `ed-toast ${kind}`;
    item.textContent = message;
    area.appendChild(item);
    setTimeout(() => {
        item.style.opacity = "0";
        item.style.transition = "opacity 0.2s";
        setTimeout(() => item.remove(), 220);
    }, 3600);
}

function setInput(element, value) {
    if (!element || document.activeElement === element) return;
    element.value = value ?? "";
}

function findClip(clipId) {
    if (!state.project || !clipId) return null;
    for (const track of state.project.tracks || []) {
        const clip = (track.clips || []).find((item) => item.id === clipId);
        if (clip) return { track, clip };
    }
    return null;
}

function projectDuration() {
    return Math.max(0, Number(state.project?.duration) || 0);
}

function clipAtPlayhead() {
    if (!state.project) return null;
    const selected = state.selectedClipId
        ? (state.project.tracks || []).find((track) => (track.clips || []).some((clip) => clip.id === state.selectedClipId))
        : null;
    const tracks = selected ? [selected, ...state.project.tracks.filter((t) => t !== selected)] : state.project.tracks;
    for (const track of tracks || []) {
        for (const clip of track.clips || []) {
            if (state.playhead > clip.start + 0.001 && state.playhead < clip.start + clip.duration - 0.001) {
                return { track, clip };
            }
        }
    }
    return null;
}

/* ------------------------------------------------------------------ status */

function renderStatus(status) {
    const button = $("#ai-status");
    state.aiConnected = Boolean(status?.connected);
    button.classList.remove("checking", "ok", "warn", "fail");
    if (status?.connected) {
        button.classList.add(status.has_matching_model ? "ok" : "warn");
        button.textContent = `IA · ${status.model || "modelo"}`;
        const models = [
            ...(status.loaded_models || []).map((name) => `${name} (carregado)`),
            ...(status.downloaded_count ? [`${status.downloaded_count} baixado(s)`] : []),
        ];
        button.title = models.join("\n") || "LM Studio conectado";
    } else {
        button.classList.add("fail");
        button.textContent = "IA offline";
        button.title = status?.error || "LM Studio inacessível";
    }
    updateChatState();
}

async function loadStatus() {
    const button = $("#ai-status");
    button.classList.add("checking");
    button.textContent = "Verificando IA...";
    try {
        renderStatus(await api("/api/editor/status"));
    } catch (error) {
        renderStatus({ connected: false, error: error.message });
    }
}

function updateChatState() {
    const label = $("#chat-state");
    if (!label) return;
    if (state.chatBusy) label.textContent = "trabalhando…";
    else if (state.aiConnected === false) label.textContent = "IA offline";
    else label.textContent = "pronta";
    $("#chat-input").disabled = state.chatBusy || !state.projectId;
    $("#chat-send").disabled = state.chatBusy || !state.projectId;
}

/* ----------------------------------------------------------------- websocket */

function connectWS() {
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    let ws;
    try {
        ws = new WebSocket(`${protocol}://${location.host}/ws`);
    } catch {
        setTimeout(connectWS, 3000);
        return;
    }
    state.ws = ws;
    ws.addEventListener("message", (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            return;
        }
        handleWS(data);
    });
    ws.addEventListener("close", () => {
        if (state.ws === ws) state.ws = null;
        setTimeout(connectWS, 2800);
    });
    ws.addEventListener("open", () => {
        setInterval(() => {
            if (state.ws?.readyState === WebSocket.OPEN) state.ws.send("ping");
        }, 25000);
    });
}

function handleWS(data) {
    if (!data || typeof data !== "object") return;
    if (data.type === "editor_project_changed") {
        if (data.project_id === state.projectId) queueRefresh();
    } else if (data.type === "editor_projects") {
        refreshProjects().catch(() => {});
    } else if (data.type === "editor_agent") {
        handleAgentEvent(data);
    } else if (data.type === "editor_chat_reset") {
        if (data.project_id === state.projectId) {
            $("#chat-messages").innerHTML = "";
        }
    }
}

function queueRefresh() {
    if (state.drag || state.mutationDepth > 0) {
        clearTimeout(state.refreshTimer);
        state.refreshTimer = setTimeout(queueRefresh, 450);
        return;
    }
    clearTimeout(state.refreshTimer);
    state.refreshTimer = setTimeout(() => refreshProject().catch(() => {}), 260);
}

/* ------------------------------------------------------------------ projeto */

async function loadProjects(preferredId = null) {
    const data = await api("/api/editor/projects");
    state.projects = data.projects || [];
    let pid = preferredId || state.projectId || data.active;
    if (pid && !state.projects.some((item) => item.id === pid)) pid = null;
    if (!pid) {
        const active = state.projects.find((item) => item.id === data.active);
        pid = active?.id || state.projects[0]?.id || null;
    }
    renderProjectSelect(pid);
    if (!pid) {
        clearProject();
        return;
    }
    const needsActivate = pid !== data.active;
    await openProject(pid, needsActivate);
}

function renderProjectSelect(pid) {
    const select = $("#project-select");
    if (!state.projects.length) {
        select.innerHTML = '<option value="">Nenhum projeto</option>';
        select.disabled = true;
        return;
    }
    select.disabled = false;
    select.innerHTML = state.projects.map((item) => (
        `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name || item.id)}</option>`
    )).join("");
    select.value = pid || "";
}

async function openProject(pid, activate = false) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    const switching = state.projectId !== pid;
    if (switching) {
        state.selectedClipId = null;
        state.selectedSourcePath = null;
        state.playhead = 0;
        state.jobs = [];
        state.versions = [];
        state.programLabel = "";
        state.openQcJobId = null;
        stopProgram();
    }
    try {
        const data = activate
            ? await api(`/api/editor/projects/${encodeURIComponent(pid)}/activate`, { method: "POST" })
            : await api(`/api/editor/projects/${encodeURIComponent(pid)}`);
        applyPayload(data);
        renderProjectSelect(pid);
        await Promise.allSettled([loadVersions(), loadJobs(), loadLatestPreview()]);
    } catch (error) {
        toast(error.message, "error");
    }
}

async function refreshProjects() {
    const data = await api("/api/editor/projects");
    state.projects = data.projects || [];
    if (state.projectId && !state.projects.some((item) => item.id === state.projectId)) {
        const pid = state.projects.find((item) => item.id === data.active)?.id || state.projects[0]?.id;
        if (pid) {
            state.projectId = null;
            await openProject(pid, pid !== data.active);
        } else {
            clearProject();
        }
        return;
    }
    if (!state.projectId && data.active) {
        await openProject(data.active, false);
        return;
    }
    renderProjectSelect(state.projectId);
}

function clearProject() {
    state.projectId = null;
    state.project = null;
    state.issues = [];
    state.history = { undo: [], redo: [] };
    state.versions = [];
    state.jobs = [];
    state.selectedClipId = null;
    state.playhead = 0;
    state.markIn = null;
    state.markOut = null;
    state.analysis = null;
    state.programLabel = "";
    stopProgram();
    stopVirtual();
    $("#tracks").innerHTML = '<div class="timeline-empty">Nenhum projeto. Crie um projeto para começar.</div>';
    $("#markers-row").innerHTML = "";
    $("#regions-row").innerHTML = "";
    $("#ruler").innerHTML = "";
    $("#playhead").hidden = true;
    $("#inspector-form").hidden = true;
    $("#inspector-empty").hidden = false;
    $("#inspector-empty").textContent = "Nenhum projeto ativo";
    $("#project-format").textContent = "—";
    $("#project-meta").textContent = "";
    $("#media-list").innerHTML = "";
    $("#issues-list").innerHTML = "";
    $("#markers-list").innerHTML = "";
    $("#regions-list").innerHTML = "";
    $("#versions-list").innerHTML = "";
    $("#history-list").innerHTML = "";
    $("#jobs-list").innerHTML = "";
    $("#qc-panel").className = "empty";
    $("#qc-panel").textContent = "Nenhum render concluído.";
    $("#job-dot").hidden = true;
    $("#undo-btn").disabled = true;
    $("#redo-btn").disabled = true;
    $("#delete-project-btn").disabled = true;
    $("#preview-btn").disabled = true;
    $("#export-btn").disabled = true;
    setInput($("#ps-name"), "");
    setInput($("#ps-width"), "");
    setInput($("#ps-height"), "");
    setInput($("#ps-fps"), "");
    updateTimeReadout();
    updateMonitor();
    updateChatState();
    updateRegionButtons();
    document.title = "ClipMind — Editor profissional";
    renderMediaList();
}

function applyPayload(data) {
    if (!data || !data.project) return;
    const previousProject = state.projectId;
    state.project = data.project;
    state.projectId = data.project.id;
    state.issues = data.issues || [];
    state.history = data.history || { undo: [], redo: [] };
    if (data.versions) state.versions = data.versions;
    if (data.jobs) setJobs(data.jobs, { notify: previousProject === state.projectId });
    if (!findClip(state.selectedClipId)) state.selectedClipId = null;
    state.playhead = clamp(state.playhead, 0, projectDuration());
    renderAll();
}

function renderAll() {
    if (!state.project) {
        clearProject();
        return;
    }
    const settings = state.project.settings || {};
    document.title = `ClipMind — ${state.project.name}`;
    $("#project-format").textContent = `${settings.width}×${settings.height} · ${settings.fps} fps`;
    const clips = (state.project.tracks || []).reduce((total, track) => total + (track.clips || []).length, 0);
    $("#project-meta").textContent = `${state.project.name} · ${fmtShort(projectDuration())} · ${clips} clipe(s)`;
    setInput($("#ps-name"), state.project.name);
    setInput($("#ps-width"), settings.width);
    setInput($("#ps-height"), settings.height);
    setInput($("#ps-fps"), settings.fps);
    $("#delete-project-btn").disabled = false;
    $("#preview-btn").disabled = false;
    $("#export-btn").disabled = false;
    renderMediaList();
    renderTimeline();
    renderInspector();
    renderIssues();
    renderMarkersPanel();
    renderRegionsPanel();
    renderVersions();
    renderHistory();
    renderJobs();
    updateTimeReadout();
    updateMonitor();
    updateChatState();
    renderProjectSelect(state.projectId);
}

async function refreshProject() {
    if (!state.projectId) return;
    const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}`);
    applyPayload(data);
}

/* ------------------------------------------------------------ mídia/skills */

async function loadUploads() {
    try {
        const data = await api("/api/editor/uploads");
        state.uploads = data.uploads || [];
    } catch {
        state.uploads = [];
    }
    renderMediaList();
}

function mediaEntries() {
    const entries = [];
    const seen = new Set();
    for (const [path, info] of Object.entries(state.project?.media || {})) {
        seen.add(path);
        entries.push({
            path,
            name: info.name || basename(path),
            info,
            inProject: true,
            kind: info.has_video ? "video" : info.has_audio ? "audio" : "other",
        });
    }
    for (const item of state.uploads) {
        if (seen.has(item.path)) continue;
        seen.add(item.path);
        entries.push({
            path: item.path,
            name: item.name || basename(item.path),
            info: null,
            inProject: false,
            kind: item.kind || mediaKind(item.path),
        });
    }
    return entries;
}

function renderMediaList() {
    const list = $("#media-list");
    const entries = mediaEntries();
    $("#media-count").textContent = entries.length ? String(entries.length) : "";
    if (!entries.length) {
        list.innerHTML = '<div class="hint">Nenhuma mídia enviada.</div>';
        return;
    }
    list.innerHTML = entries.map((entry) => {
        const info = entry.info;
        const detail = info
            ? `${fmtShort(info.duration)} · ${info.width || 0}×${info.height || 0}`
            : (entry.kind === "audio" ? "áudio" : "vídeo");
        const canVideo = info ? Boolean(info.has_video) : entry.kind !== "audio";
        const canAudio = info ? Boolean(info.has_audio) : entry.kind !== "other";
        const active = entry.path === state.selectedSourcePath ? " selected" : "";
        const buttons = [
            canVideo ? `<button type="button" data-add-track="v1" data-path="${escapeHtml(entry.path)}">V1</button>` : "",
            canVideo ? `<button type="button" data-add-track="v2" data-path="${escapeHtml(entry.path)}">V2</button>` : "",
            canAudio ? `<button type="button" data-add-track="a1" data-path="${escapeHtml(entry.path)}">A1</button>` : "",
        ].join("");
        return `
            <div class="media-item${active}" data-media-path="${escapeHtml(entry.path)}">
                <button class="media-name" type="button" data-source="${escapeHtml(entry.path)}" title="${escapeHtml(entry.path)}">
                    ${escapeHtml(entry.name)}${entry.inProject ? '<span class="media-badge">projeto</span>' : ""}
                </button>
                <span class="media-sub">${escapeHtml(detail)}</span>
                <div class="media-actions">${buttons || '<span class="media-sub">sem trilhas compatíveis</span>'}</div>
            </div>`;
    }).join("");
}

async function loadSkills() {
    try {
        const data = await api("/api/editor/skills");
        state.skills = data.skills || [];
    } catch {
        state.skills = [];
    }
    renderSkills();
}

function renderSkills() {
    const list = $("#skills-list");
    const total = state.skills.length;
    const complete = state.skills.filter((skill) => skill.complete).length;
    $("#skill-count").textContent = total ? `${complete}/${total}` : "";
    if (!total) {
        list.innerHTML = '<div class="hint">Nenhuma skill instalada.</div>';
        return;
    }
    list.innerHTML = state.skills.map((skill) => `
        <div class="skill-item">
            <button type="button" data-skill="${escapeHtml(skill.name)}">${escapeHtml(skill.title || skill.name)}</button>
            <span class="skill-desc">${escapeHtml(skill.description || "")}</span>
            ${skill.complete ? "" : '<span class="skill-desc">incompleta</span>'}
        </div>`).join("");
}

async function openSkill(name) {
    try {
        const data = await api(`/api/editor/skills/${encodeURIComponent(name)}`);
        $("#skill-title").textContent = data.title || name;
        $("#skill-meta").textContent = `${data.sections || 0}/10 seções${data.complete ? "" : " · incompleta"}`;
        $("#skill-content").textContent = data.content || "";
        const dialog = $("#skill-dialog");
        if (!dialog.open) dialog.showModal();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function addMedia(source, trackId) {
    if (!state.projectId) {
        toast("Crie um projeto primeiro", "error");
        return;
    }
    try {
        await operation("add_clip", { track_id: trackId, source });
        const track = state.project?.tracks?.find((item) => item.id === trackId);
        const last = track?.clips?.[track.clips.length - 1];
        if (last) selectClip(last.id, { openInspector: false });
        toast(`Mídia adicionada em ${trackId}`, "ok");
        renderMediaList();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function addSubtitleFile(path) {
    if (!state.projectId) {
        toast("Crie um projeto primeiro", "error");
        return;
    }
    try {
        await operation("add_subtitles", {
            track_id: "s1",
            subtitle_path: path,
            start: state.playhead,
            font_size: 22,
            position: "inferior",
            margin_v: 42,
        });
        $("#subtitle-state").textContent = basename(path);
        toast("Legendas adicionadas", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function uploadFiles(files, asSubtitle = false) {
    const list = Array.from(files || []);
    if (!list.length) return;
    for (const file of list) {
        try {
            const form = new FormData();
            form.append("file", file);
            const response = await fetch("/upload", { method: "POST", body: form });
            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const data = await response.json();
                    detail = data.detail || detail;
                } catch {
                    // resposta sem JSON: mantém o status
                }
                throw new Error(detail);
            }
            const data = await response.json();
            if (asSubtitle) {
                await addSubtitleFile(data.file_path);
            } else {
                await addMedia(data.file_path, isAudioPath(data.file_path) ? "a1" : "v1");
            }
        } catch (error) {
            toast(`${file.name}: ${error.message}`, "error");
        }
    }
    await loadUploads();
}

/* ---------------------------------------------------------------- timeline */

function contentHeightOffset() {
    return HEADER_W;
}

function renderTimeline() {
    if (!state.project) return;
    const duration = Math.max(10, projectDuration());
    const width = HEADER_W + duration * state.pps + 260;
    $("#timeline-content").style.width = `${width}px`;
    renderRuler(duration);
    renderMarkersRow();
    renderRegionsRow();
    renderTracks();
    updatePlayhead();
    $("#undo-btn").disabled = !state.history.undo?.length;
    $("#redo-btn").disabled = !state.history.redo?.length;
    $("#undo-btn").title = state.history.undo?.length ? `Desfazer: ${state.history.undo[0]}` : "Nada para desfazer";
    $("#redo-btn").title = state.history.redo?.length ? `Refazer: ${state.history.redo[0]}` : "Nada para refazer";
    $("#timeline-hint").textContent = `${fmtShort(projectDuration())} · ${state.snap ? "ímã ligado" : "ímã desligado"}`;
    updateTimeReadout();
}

function renderRuler(duration) {
    const ruler = $("#ruler");
    const step = RULER_STEPS.find((value) => value * state.pps >= 62) || 600;
    const minor = step / 2;
    const parts = [`<div class="ruler-spacer">${fmtShort(duration)}</div>`];
    for (let time = 0; time <= duration + step; time += step) {
        const left = HEADER_W + time * state.pps;
        parts.push(`<div class="ruler-tick major" style="left:${left}px"></div>`);
        parts.push(`<div class="ruler-label" style="left:${left}px">${fmtRuler(time)}</div>`);
        if (minor * state.pps >= 24) {
            const mid = HEADER_W + (time + minor) * state.pps;
            parts.push(`<div class="ruler-tick" style="left:${mid}px"></div>`);
        }
    }
    ruler.innerHTML = parts.join("");
}

function renderMarkersRow() {
    const row = $("#markers-row");
    const markers = state.project?.markers || [];
    const parts = [`<div class="ruler-spacer" style="height:100%">M</div>`];
    for (const marker of markers) {
        const left = HEADER_W + Number(marker.time) * state.pps;
        const cor = escapeHtml(marker.color || "#fbbf24");
        parts.push(`<button type="button" class="marker-pin" data-marker="${escapeHtml(marker.id)}" style="left:${left}px;background:${cor}" title="${escapeHtml(marker.label || fmtTime(marker.time))}"></button>`);
        if (marker.label) {
            parts.push(`<span class="marker-label" style="left:${left}px;color:${cor}">${escapeHtml(marker.label)}</span>`);
        }
    }
    row.innerHTML = parts.join("");
}

function renderRegionsRow() {
    const row = $("#regions-row");
    const regions = state.project?.regions || [];
    const parts = [`<div class="ruler-spacer" style="height:100%">R</div>`];
    for (const region of regions) {
        const left = HEADER_W + Number(region.start) * state.pps;
        const width = Math.max(4, (Number(region.end) - Number(region.start)) * state.pps);
        const cor = escapeHtml(region.color || "#4f8cff");
        const titulo = `${region.label || "Região"} · ${fmtTime(region.start, true)} → ${fmtTime(region.end, true)}`;
        parts.push(`<button type="button" class="region-band" data-region="${escapeHtml(region.id)}" style="left:${left}px;width:${width}px;color:${cor}" title="${escapeHtml(titulo)}"><span>${escapeHtml(region.label || "")}</span></button>`);
    }
    row.innerHTML = parts.join("");
}

function renderTracks() {
    const tracks = state.project?.tracks || [];
    if (!tracks.length) {
        $("#tracks").innerHTML = '<div class="timeline-empty">Projeto sem faixas.</div>';
        return;
    }
    $("#tracks").innerHTML = tracks.map((track) => {
        const clips = track.clips || [];
        const clipHtml = clips.map((clip) => {
            const width = Math.max(3, clip.duration * state.pps);
            const left = clip.start * state.pps;
            const selected = clip.id === state.selectedClipId ? " selected" : "";
            const missing = clip.missing ? " missing" : "";
            const label = clip.type === "text"
                ? (clip.text?.content || "Título")
                : (clip.name || clip.id);
            const sub = clip.type === "text" || clip.type === "subtitle"
                ? fmtShort(clip.duration)
                : `${fmtShort(clip.duration)} · ${Number(clip.speed || 1).toFixed(2)}×`;
            const leftHandle = clip.type === "video" || clip.type === "audio"
                ? '<div class="clip-handle left" data-handle="left"></div>' : "";
            const title = clip.type === "text"
                ? label
                : `${clip.name || ""}\n${fmtTime(clip.start, true)} → ${fmtTime(clip.start + clip.duration, true)}`;
            return `
                <div class="clip ${escapeHtml(clip.type)}${selected}${missing}" data-clip="${escapeHtml(clip.id)}" style="left:${left}px;width:${width}px" title="${escapeHtml(title)}">
                    ${leftHandle}
                    <div class="clip-label">${escapeHtml(label)}</div>
                    ${width > 70 ? `<div class="clip-sub">${escapeHtml(sub)}</div>` : ""}
                    <div class="clip-handle right" data-handle="right"></div>
                </div>`;
        }).join("");
        const muteButton = ["video", "audio"].includes(track.type)
            ? `<button type="button" data-track-action="muted" class="${track.muted ? "on" : ""}" title="Mudo">M</button>` : "";
        const hideButton = ["video", "text", "subtitle"].includes(track.type)
            ? `<button type="button" data-track-action="hidden" class="${track.hidden ? "on" : ""}" title="Ocultar">O</button>` : "";
        return `
            <div class="track-row ${escapeHtml(track.type)}${track.hidden ? " hidden-track" : ""}${track.locked ? " locked" : ""}" data-track="${escapeHtml(track.id)}">
                <div class="track-header">
                    <div class="track-title"><span class="track-type-dot"></span><span class="track-name">${escapeHtml(track.id)} · ${escapeHtml(track.name)}</span></div>
                    <div class="track-tools">
                        ${muteButton}${hideButton}
                        <button type="button" data-track-action="locked" class="${track.locked ? "on" : ""}" title="Bloquear">L</button>
                    </div>
                </div>
                <div class="track-lane" data-lane="${escapeHtml(track.id)}">${clipHtml}</div>
            </div>`;
    }).join("");
}

function updatePlayhead() {
    const playhead = $("#playhead");
    if (!state.project) {
        playhead.hidden = true;
        return;
    }
    playhead.hidden = false;
    playhead.style.left = `${HEADER_W + state.playhead * state.pps}px`;
}

function updateTimeReadout() {
    const readout = $("#time-readout");
    readout.textContent = `${fmtTime(state.playhead, true)} / ${fmtTime(projectDuration(), true)}`;
}

function setPlayhead(seconds, { seek = true } = {}) {
    const max = projectDuration();
    state.playhead = clamp(Number(seconds) || 0, 0, max);
    updatePlayhead();
    updateTimeReadout();
    if (seek) seekProgram(state.playhead);
}

function seekProgram(seconds) {
    const video = $("#program-video");
    if (!video.getAttribute("src")) return;
    try {
        const limit = Number.isFinite(video.duration) && video.duration > 0 ? video.duration : seconds;
        video.currentTime = clamp(seconds, 0, Math.max(0, limit - 0.01));
    } catch {
        // mídia ainda sem metadados
    }
}

function snapTargets(excludeId) {
    const times = [0, state.playhead];
    for (const marker of state.project?.markers || []) times.push(Number(marker.time));
    for (const region of state.project?.regions || []) {
        times.push(Number(region.start));
        times.push(Number(region.end));
    }
    for (const track of state.project?.tracks || []) {
        for (const clip of track.clips || []) {
            if (clip.id === excludeId) continue;
            times.push(Number(clip.start));
            times.push(Number(clip.start) + Number(clip.duration));
        }
    }
    return times;
}

function snapTime(value, excludeId) {
    if (!state.snap) return value;
    const threshold = 8 / state.pps;
    let best = value;
    let distance = threshold;
    for (const target of snapTargets(excludeId)) {
        const delta = Math.abs(target - value);
        if (delta < distance) {
            best = target;
            distance = delta;
        }
    }
    return best;
}

function snapMove(start, duration, excludeId) {
    if (!state.snap) return Math.max(0, start);
    const threshold = 8 / state.pps;
    let best = start;
    let distance = threshold;
    for (const target of snapTargets(excludeId)) {
        const startDelta = Math.abs(target - start);
        if (startDelta < distance) {
            best = target;
            distance = startDelta;
        }
        const endDelta = Math.abs(target - (start + duration));
        if (endDelta < distance) {
            best = target - duration;
            distance = endDelta;
        }
    }
    return Math.max(0, best);
}

function onTimelinePointerDown(event) {
    if (event.button !== 0) return;
    const trackButton = event.target.closest("[data-track-action]");
    if (trackButton) {
        const row = trackButton.closest(".track-row");
        const track = state.project?.tracks?.find((item) => item.id === row?.dataset.track);
        if (!track) return;
        const action = trackButton.dataset.trackAction;
        operation("set_track", { track_id: track.id, [action]: !track[action] }).catch((error) => toast(error.message, "error"));
        return;
    }

    const marker = event.target.closest(".marker-pin");
    if (marker) {
        const found = (state.project?.markers || []).find((item) => item.id === marker.dataset.marker);
        if (found) setPlayhead(Number(found.time));
        return;
    }

    const band = event.target.closest(".region-band");
    if (band) {
        const found = (state.project?.regions || []).find((item) => item.id === band.dataset.region);
        if (found) setPlayhead(Number(found.start));
        return;
    }

    const ruler = event.target.closest(".ruler");
    if (ruler && !event.target.closest(".ruler-spacer")) {
        const startSeek = makeSeekDrag(event, ruler, true);
        startSeek(event);
        return;
    }

    const clipElement = event.target.closest(".clip");
    if (clipElement) {
        const clipId = clipElement.dataset.clip;
        const found = findClip(clipId);
        if (!found) return;
        selectClip(clipId);
        if (found.track.locked) {
            toast("Faixa bloqueada", "error");
            return;
        }
        const handle = event.target.closest(".clip-handle");
        beginClipDrag(event, found, clipElement, handle ? handle.dataset.handle : "move");
        return;
    }

    const lane = event.target.closest(".track-lane");
    if (lane) {
        const startSeek = makeSeekDrag(event, lane, false);
        startSeek(event);
    }
}

function makeSeekDrag(originEvent, element, ruler) {
    const rect = element.getBoundingClientRect();
    const toTime = (clientX) => {
        const x = clientX - rect.left;
        return (x - (ruler ? HEADER_W : 0)) / state.pps;
    };
    return (event) => {
        setPlayhead(Math.max(0, toTime(event.clientX)));
        const move = (moveEvent) => setPlayhead(Math.max(0, toTime(moveEvent.clientX)));
        const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up, { once: true });
    };
}

function beginClipDrag(event, found, element, mode) {
    const { clip } = found;
    if (mode === "left" && (clip.type === "text" || clip.type === "subtitle")) return;
    event.preventDefault();
    const speed = Math.max(0.01, Number(clip.speed) || 1);
    const originalIn = Number(clip.in) || 0;
    const originalOut = Number(clip.out) || 0;
    const drag = {
        mode,
        clipId: clip.id,
        clip,
        element,
        startX: event.clientX,
        origStart: Number(clip.start) || 0,
        origDur: Number(clip.duration) || 0,
        origIn: originalIn,
        origOut: originalOut,
        speed,
        type: clip.type,
        sourceDuration: Number(clip.source_duration) || 0,
        newStart: Number(clip.start) || 0,
        newIn: originalIn,
        newOut: originalOut,
        newDur: Number(clip.duration) || 0,
        moved: false,
    };
    state.drag = drag;
    document.body.classList.add(mode === "move" ? "dragging" : "trimming");
    window.addEventListener("pointermove", onClipDragMove);
    window.addEventListener("pointerup", onClipDragEnd, { once: true });
}

function onClipDragMove(event) {
    const drag = state.drag;
    if (!drag) return;
    const dx = event.clientX - drag.startX;
    if (Math.abs(dx) < 2 && !drag.moved) return;
    drag.moved = true;
    const delta = dx / state.pps;

    if (drag.mode === "move") {
        let start = Math.max(0, drag.origStart + delta);
        start = snapMove(start, drag.origDur, drag.clipId);
        drag.newStart = start;
        drag.element.style.left = `${start * state.pps}px`;
        $("#timeline-hint").textContent = `Mover para ${fmtTime(start, true)}`;
        return;
    }

    if (drag.mode === "right") {
        let end = drag.origStart + drag.origDur + delta;
        const minEnd = drag.origStart + 0.05;
        let maxEnd = Infinity;
        if (drag.type === "video" || drag.type === "audio") {
            maxEnd = drag.origStart + Math.max(0.05, (drag.sourceDuration - drag.origIn) / drag.speed);
        }
        end = clamp(end, minEnd, maxEnd);
        end = snapTime(end, drag.clipId);
        end = clamp(end, minEnd, maxEnd);
        drag.newDur = end - drag.origStart;
        drag.element.style.width = `${Math.max(3, drag.newDur * state.pps)}px`;
        if (drag.type === "video" || drag.type === "audio") {
            drag.newOut = drag.origIn + drag.newDur * drag.speed;
        }
        $("#timeline-hint").textContent = `Duração ${fmtTime(drag.newDur, true)}`;
        return;
    }

    if (drag.mode === "left") {
        let start = Math.max(0, drag.origStart + delta);
        start = snapTime(start, drag.clipId);
        const shift = start - drag.origStart;
        let nextIn = drag.origIn + shift * drag.speed;
        nextIn = clamp(nextIn, 0, drag.origOut - 0.05 * drag.speed);
        start = drag.origStart + (nextIn - drag.origIn) / drag.speed;
        drag.newStart = start;
        drag.newIn = nextIn;
        drag.newDur = drag.origDur - shift;
        drag.element.style.left = `${start * state.pps}px`;
        drag.element.style.width = `${Math.max(3, (drag.origStart + drag.origDur - start) * state.pps)}px`;
        $("#timeline-hint").textContent = `Entrada ${fmtTime(nextIn, true)}`;
    }
}

async function onClipDragEnd() {
    window.removeEventListener("pointermove", onClipDragMove);
    document.body.classList.remove("dragging", "trimming");
    const drag = state.drag;
    state.drag = null;
    if (!drag || !drag.moved) return;
    try {
        if (drag.mode === "move") {
            await operation("move", { clip_id: drag.clipId, start: Number(drag.newStart.toFixed(3)) });
        } else if (drag.mode === "left") {
            await operation("trim", {
                clip_id: drag.clipId,
                in_point: Number(drag.newIn.toFixed(3)),
                shift_start: true,
            });
        } else if (drag.type === "video" || drag.type === "audio") {
            await operation("trim", {
                clip_id: drag.clipId,
                out_point: Number(drag.newOut.toFixed(3)),
            });
        } else {
            await operation("trim", {
                clip_id: drag.clipId,
                duration: Number(drag.newDur.toFixed(3)),
            });
        }
    } catch (error) {
        toast(error.message, "error");
        await refreshProject().catch(() => {});
    }
}

function selectClip(clipId, { openInspector = true } = {}) {
    if (clipId !== state.selectedClipId) {
        state.analysis = null;
        state.analysisKind = "scenes";
    }
    state.selectedClipId = clipId;
    $$(".clip").forEach((element) => element.classList.toggle("selected", element.dataset.clip === clipId));
    renderInspector();
    if (openInspector) activateRightTab("inspector");
}

/* --------------------------------------------------------------- operações */

async function operation(name, params = {}, { render = true } = {}) {
    if (!state.projectId) throw new Error("Crie um projeto primeiro");
    const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/operations`, {
        method: "POST",
        body: { operation: name, params },
    });
    if (render) applyPayload(data);
    return data;
}

async function undo() {
    if (!state.projectId) return;
    try {
        applyPayload(await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/undo`, { method: "POST" }));
    } catch (error) {
        toast(error.message, "error");
    }
}

async function redo() {
    if (!state.projectId) return;
    try {
        applyPayload(await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/redo`, { method: "POST" }));
    } catch (error) {
        toast(error.message, "error");
    }
}

async function splitAtPlayhead() {
    if (!state.project) return;
    const under = clipAtPlayhead();
    const found = under || findClip(state.selectedClipId);
    if (!found) {
        toast("Nenhum clipe no playhead", "error");
        return;
    }
    if (!["video", "audio"].includes(found.clip.type)) {
        toast("Só clipes de mídia podem ser divididos", "error");
        return;
    }
    try {
        await operation("split", { clip_id: found.clip.id, at: Number(state.playhead.toFixed(3)) });
        selectClip(found.clip.id, { openInspector: false });
    } catch (error) {
        toast(error.message, "error");
    }
}

async function duplicateSelected() {
    const found = findClip(state.selectedClipId);
    if (!found) {
        toast("Selecione um clipe", "error");
        return;
    }
    try {
        const data = await operation("duplicate", { clip_id: found.clip.id, ripple: true });
        const track = data.project.tracks.find((item) => item.id === found.track.id);
        const clips = track?.clips || [];
        const candidates = clips.filter((clip) => clip.source === found.clip.source || clip.type === found.clip.type);
        if (candidates.length) selectClip(candidates[candidates.length - 1].id, { openInspector: false });
    } catch (error) {
        toast(error.message, "error");
    }
}

async function deleteSelected() {
    const found = findClip(state.selectedClipId);
    if (!found) {
        toast("Selecione um clipe", "error");
        return;
    }
    const label = found.clip.type === "text" ? found.clip.text?.content : found.clip.name;
    const confirmed = await confirmDialog(
        "Excluir clipe",
        `Remover "${truncate(label || found.clip.id, 80)}" da timeline? A ação pode ser desfeita com Ctrl+Z.`,
        "Excluir",
    );
    if (!confirmed) return;
    try {
        await operation("delete", { clip_id: found.clip.id });
        state.selectedClipId = null;
        renderInspector();
    } catch (error) {
        toast(error.message, "error");
    }
}

async function addMarker() {
    if (!state.projectId) return;
    const label = $("#marker-label").value.trim();
    try {
        await operation("add_marker", { time: Number(state.playhead.toFixed(3)), label });
        $("#marker-label").value = "";
    } catch (error) {
        toast(error.message, "error");
    }
}

function updateRegionButtons() {
    $("#mark-in-btn").textContent = state.markIn === null ? "Entrada" : `Entrada ${fmtShort(state.markIn)}`;
    $("#mark-out-btn").textContent = state.markOut === null ? "Saída" : `Saída ${fmtShort(state.markOut)}`;
    $("#region-btn").disabled = state.markIn === null || state.markOut === null;
}

function markRegion(which) {
    state[which] = Number(state.playhead.toFixed(3));
    updateRegionButtons();
}

async function addRegion() {
    if (state.markIn === null || state.markOut === null) return;
    const start = Math.min(state.markIn, state.markOut);
    const end = Math.max(state.markIn, state.markOut);
    try {
        await operation("add_region", { start, end, label: "" });
        state.markIn = null;
        state.markOut = null;
        updateRegionButtons();
    } catch (error) {
        toast(error.message, "error");
    }
}

function selectSource(path) {
    state.selectedSourcePath = path;
    state.sourceLabel = basename(path);
    const video = $("#source-video");
    video.src = `/api/editor/media?path=${encodeURIComponent(path)}`;
    activateMonitor("source");
    renderMediaList();
    updateMonitor();
}

/* ----------------------------------------------------------------- inspetor */

function inspectorField(label, name, value, options = {}) {
    const type = options.type || "number";
    const attrs = [
        options.min !== undefined ? `min="${options.min}"` : "",
        options.max !== undefined ? `max="${options.max}"` : "",
        options.step !== undefined ? `step="${options.step}"` : "",
        options.readonly ? "readonly" : "",
    ].join(" ");
    if (type === "select") {
        return `<label class="ed-field">${label}<select name="${name}">${options.options || ""}</select></label>`;
    }
    if (type === "textarea") {
        return `<label class="ed-field">${label}<textarea name="${name}">${escapeHtml(value)}</textarea></label>`;
    }
    return `<label class="ed-field">${label}<input type="${type}" name="${name}" value="${escapeHtml(value)}" ${attrs}></label>`;
}

function option(value, label, current) {
    return `<option value="${escapeHtml(value)}"${String(value) === String(current) ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

function renderInspector() {
    const form = $("#inspector-form");
    const empty = $("#inspector-empty");
    const found = findClip(state.selectedClipId);
    if (!found) {
        form.hidden = true;
        empty.hidden = false;
        empty.textContent = state.project ? "Nenhum clipe selecionado" : "Nenhum projeto ativo";
        return;
    }
    empty.hidden = true;
    form.hidden = false;
    const { clip } = found;
    const typeLabels = { video: "vídeo", audio: "áudio", text: "título", subtitle: "legenda" };
    const html = [];
    html.push(`
        <div class="insp-head">
            <strong title="${escapeHtml(clip.name || clip.id)}">${escapeHtml(clip.name || clip.id)}</strong>
            <span class="insp-type">${typeLabels[clip.type] || clip.type}</span>
            <span class="muted">${escapeHtml(clip.id)}</span>
        </div>`);

    html.push('<div class="insp-group"><h4>Tempo</h4><div class="ed-grid-3">');
    html.push(inspectorField("Início (s)", "start", clip.start.toFixed(3), { min: 0, step: 0.01 }));
    if (clip.type === "video" || clip.type === "audio") {
        html.push(inspectorField("Duração (s)", "duration", clip.duration.toFixed(3), { min: 0.05, step: 0.01 }));
        html.push(inspectorField("Fonte entrada", "in", Number(clip.in).toFixed(3), { min: 0, step: 0.01 }));
        html.push(inspectorField("Fonte saída", "out", Number(clip.out).toFixed(3), { min: 0, step: 0.01 }));
        html.push(inspectorField("Velocidade", "speed", clip.speed, { min: 0.1, max: 8, step: 0.05 }));
        html.push(inspectorField("Fonte (s)", "source_duration", Number(clip.source_duration || 0).toFixed(3), { readonly: true, step: 0.01 }));
    } else {
        html.push(inspectorField("Duração (s)", "duration", clip.duration.toFixed(3), { min: 0.2, step: 0.01 }));
    }
    html.push("</div></div>");

    if (clip.type === "video" || clip.type === "audio") {
        html.push('<div class="insp-group"><h4>Áudio</h4><div class="ed-grid-2">');
        html.push(inspectorField("Volume", "volume", clip.volume, { min: 0, max: 4, step: 0.05 }));
        html.push(inspectorField("Fade in (s)", "fade_in", clip.fade_in, { min: 0, step: 0.05 }));
        html.push(inspectorField("Fade out (s)", "fade_out", clip.fade_out, { min: 0, step: 0.05 }));
        html.push(`<label class="check" style="align-self:flex-end;padding-bottom:7px"><input type="checkbox" name="muted" ${clip.muted ? "checked" : ""}> Mudo</label>`);
        html.push("</div></div>");
    }

    if (clip.type === "video") {
        const transform = clip.transform || {};
        html.push('<div class="insp-group"><h4>Transformação</h4><div class="ed-grid-3">');
        html.push(inspectorField("Escala", "transform_scale", transform.scale ?? 1, { min: 0.05, max: 8, step: 0.01 }));
        html.push(inspectorField("X (px)", "transform_x", transform.x ?? 0, { step: 1 }));
        html.push(inspectorField("Y (px)", "transform_y", transform.y ?? 0, { step: 1 }));
        html.push(inspectorField("Rotação", "transform_rotation", transform.rotation ?? 0, { step: 1 }));
        html.push(inspectorField("Opacidade", "transform_opacity", transform.opacity ?? 1, { min: 0, max: 1, step: 0.05 }));
        html.push("</div></div>");

        const color = clip.color || {};
        html.push('<div class="insp-group"><h4>Cor</h4><div class="ed-grid-2">');
        html.push(inspectorField("Brilho", "color_brightness", color.brightness ?? 0, { min: -1, max: 1, step: 0.01 }));
        html.push(inspectorField("Contraste", "color_contrast", color.contrast ?? 1, { min: 0, max: 4, step: 0.01 }));
        html.push(inspectorField("Saturação", "color_saturation", color.saturation ?? 1, { min: 0, max: 4, step: 0.01 }));
        html.push(inspectorField("Gamma", "color_gamma", color.gamma ?? 1, { min: 0.1, max: 10, step: 0.01 }));
        html.push("</div></div>");

        const transition = clip.transition || { type: "none", duration: 0 };
        html.push('<div class="insp-group"><h4>Transição</h4><div class="ed-grid-2">');
        html.push(inspectorField("Tipo", "transition_type", transition.type, {
            type: "select",
            options: option("none", "Nenhuma", transition.type) + option("fade", "Fade", transition.type),
        }));
        html.push(inspectorField("Duração (s)", "transition_duration", transition.duration ?? 0, { min: 0, step: 0.05 }));
        html.push("</div></div>");
    }

    if (clip.type === "text") {
        const text = clip.text || {};
        html.push('<div class="insp-group"><h4>Título</h4>');
        html.push(inspectorField("Texto", "text", text.content || "", { type: "textarea" }));
        html.push('<div class="ed-grid-2">');
        html.push(inspectorField("Tamanho", "font_size", text.font_size ?? 56, { min: 8, max: 300, step: 1 }));
        html.push(inspectorField("Cor", "text_color", text.color || "white", { type: "text" }));
        html.push(inspectorField("Posição", "position", text.position, {
            type: "select",
            options: ["inferior", "topo", "centro", "inferior-esquerda", "inferior-direita"]
                .map((value) => option(value, value, text.position)).join(""),
        }));
        html.push(`<label class="check" style="align-self:flex-end;padding-bottom:7px"><input type="checkbox" name="background" ${text.background ? "checked" : ""}> Fundo</label>`);
        html.push("</div></div>");
    }

    if (clip.type === "subtitle") {
        const subtitle = clip.subtitle || {};
        html.push('<div class="insp-group"><h4>Legenda</h4><div class="ed-grid-2">');
        html.push(inspectorField("Tamanho", "subtitle_font_size", subtitle.font_size ?? 22, { min: 8, max: 120, step: 1 }));
        html.push(inspectorField("Cor", "subtitle_color", subtitle.color || "white", { type: "text" }));
        html.push(inspectorField("Posição", "subtitle_position", subtitle.position || "inferior", {
            type: "select",
            options: ["inferior", "centro", "topo"].map((value) => option(value, value, subtitle.position)).join(""),
        }));
        html.push(inspectorField("Margem vertical", "subtitle_margin_v", subtitle.margin_v ?? 42, { min: 0, max: 400, step: 1 }));
        html.push("</div></div>");
    }

    const midia = clip.type === "video" || clip.type === "audio";
    if (midia) {
        html.push(renderAnalysisGroup());
    }

    html.push(`
        <div class="form-actions">
            <button type="button" id="insp-duplicate" class="btn btn-small btn-ghost">Duplicar</button>
            <button type="button" id="insp-delete" class="btn btn-small danger">Excluir</button>
            <button type="submit" class="btn btn-small btn-primary">Aplicar</button>
        </div>`);
    form.innerHTML = html.join("");
    $("#insp-duplicate", form).addEventListener("click", duplicateSelected);
    $("#insp-delete", form).addEventListener("click", deleteSelected);
    if (midia) wireAnalysis(clip);
    form.onsubmit = (event) => {
        event.preventDefault();
        applyInspector().catch((error) => toast(error.message, "error"));
    };
}

async function applyInspector() {
    const found = findClip(state.selectedClipId);
    if (!found) return;
    const { clip } = found;
    const form = $("#inspector-form");
    const data = Object.fromEntries(new FormData(form).entries());
    const props = {};
    const ops = [];

    if (clip.type === "video" || clip.type === "audio") {
        const newStart = num(data.start, clip.start);
        const newDur = num(data.duration, clip.duration);
        const newIn = num(data.in, clip.in);
        const newOut = num(data.out, clip.out);
        const newSpeed = num(data.speed, clip.speed);
        const durationChanged = differs(newDur, clip.duration);
        const inChanged = differs(newIn, clip.in);
        const outChanged = differs(newOut, clip.out);
        let targetIn = newIn;
        let targetOut = newOut;
        if (durationChanged) targetOut = newIn + newDur * newSpeed;
        if (differs(targetIn, clip.in) || differs(targetOut, clip.out)) {
            ops.push(["trim", { clip_id: clip.id, in_point: targetIn, out_point: targetOut }]);
        }
        if (differs(newStart, clip.start)) ops.push(["move", { clip_id: clip.id, start: newStart }]);
        if (differs(newSpeed, clip.speed)) props.speed = newSpeed;

        for (const key of ["volume", "fade_in", "fade_out"]) {
            const value = num(data[key], clip[key]);
            if (differs(value, clip[key])) props[key] = value;
        }
        const muted = form.elements.namedItem("muted")?.checked || false;
        if (Boolean(muted) !== Boolean(clip.muted)) props.muted = muted;

        if (clip.type === "video") {
            const transform = clip.transform || {};
            for (const [key, def] of [["scale", 1], ["x", 0], ["y", 0], ["rotation", 0], ["opacity", 1]]) {
                const value = num(data[`transform_${key}`], transform[key] ?? def);
                if (differs(value, transform[key] ?? def)) props[`transform_${key}`] = value;
            }
            const color = clip.color || {};
            for (const [key, def] of [["brightness", 0], ["contrast", 1], ["saturation", 1], ["gamma", 1]]) {
                const value = num(data[`color_${key}`], color[key] ?? def);
                if (differs(value, color[key] ?? def)) props[`color_${key}`] = value;
            }
            const transition = clip.transition || { type: "none", duration: 0 };
            const type = data.transition_type || transition.type;
            const duration = num(data.transition_duration, transition.duration);
            if (type !== transition.type || differs(duration, transition.duration)) {
                props.transition = { type, duration };
            }
        }
    } else {
        const newStart = num(data.start, clip.start);
        const newDuration = num(data.duration, clip.duration);
        if (differs(newDuration, clip.duration)) ops.push(["trim", { clip_id: clip.id, duration: newDuration }]);
        if (differs(newStart, clip.start)) ops.push(["move", { clip_id: clip.id, start: newStart }]);

        if (clip.type === "text") {
            const text = clip.text || {};
            if ((data.text || "").trim() !== text.content) props.text = data.text || "";
            if (differs(num(data.font_size, text.font_size), text.font_size)) props.font_size = num(data.font_size);
            if ((data.text_color || "") !== (text.color || "")) props.text_color = data.text_color;
            if ((data.position || "") !== (text.position || "")) props.position = data.position;
            const background = form.elements.namedItem("background")?.checked || false;
            if (Boolean(background) !== Boolean(text.background)) props.background = background;
        } else if (clip.type === "subtitle") {
            const subtitle = clip.subtitle || {};
            if (differs(num(data.subtitle_font_size, subtitle.font_size), subtitle.font_size)) {
                props.subtitle_font_size = num(data.subtitle_font_size);
            }
            if ((data.subtitle_color || "") !== (subtitle.color || "")) props.subtitle_color = data.subtitle_color;
            if ((data.subtitle_position || "") !== (subtitle.position || "")) props.subtitle_position = data.subtitle_position;
            if (differs(num(data.subtitle_margin_v, subtitle.margin_v), subtitle.margin_v)) {
                props.subtitle_margin_v = num(data.subtitle_margin_v);
            }
        }
    }

    if (!ops.length && !Object.keys(props).length) return;
    state.mutationDepth += 1;
    try {
        for (const [name, params] of ops) {
            await operation(name, params);
        }
        if (Object.keys(props).length) {
            await operation("set", { clip_id: clip.id, ...props });
        }
        toast("Clipe atualizado", "ok");
    } finally {
        state.mutationDepth = Math.max(0, state.mutationDepth - 1);
    }
}

/* ------------------------------------------------------------------ análise */

const ANALISES = [
    ["scenes", "Cortes de cena"],
    ["silence", "Pausas de silêncio"],
    ["loudness", "Loudness"],
];

function renderAnalysisGroup() {
    const valores = ANALISES.map(([value, label]) => option(value, label, state.analysisKind)).join("");
    return [
        '<div class="insp-group"><h4>Análise</h4><div class="analysis-row">',
        `<select id="analysis-kind">${valores}</select>`,
        '<label class="ed-field analysis-field" data-kind="scenes">Limiar<input id="analysis-threshold" type="number" min="1" max="100" step="1" value="15"></label>',
        '<label class="ed-field analysis-field" data-kind="silence">Pausa mín. (s)<input id="analysis-min-pause" type="number" min="0.05" max="60" step="0.05" value="0.5"></label>',
        '<label class="ed-field analysis-field" data-kind="silence">Ruído (dB)<input id="analysis-noise" type="number" min="-90" max="0" step="1" value="-30"></label>',
        `<button type="button" class="btn btn-small" id="analysis-run"${state.analyzing ? " disabled" : ""}>${state.analyzing ? "Medindo…" : "Medir"}</button>`,
        '</div><div class="analysis-results" id="analysis-results"></div></div>',
    ].join("");
}

function syncAnalysisFields() {
    $$(".analysis-field").forEach((field) => {
        field.hidden = field.dataset.kind !== state.analysisKind;
    });
}

function analysisValue(id, fallback) {
    const input = $(id);
    const value = Number(input?.value);
    return Number.isFinite(value) ? value : fallback;
}

async function runAnalysis(clip, { apply = false } = {}) {
    if (!state.projectId || state.analyzing) return;
    state.analyzing = true;
    renderInspector();
    try {
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/analyze`, {
            method: "POST",
            body: {
                clip_id: clip.id,
                kind: state.analysisKind,
                threshold: analysisValue("#analysis-threshold", 15),
                min_pause: analysisValue("#analysis-min-pause", 0.5),
                noise: analysisValue("#analysis-noise", -30),
                apply,
            },
        });
        state.analysis = data.analysis;
        state.analyzing = false;
        applyPayload(data);
        const gravadas = data.annotations;
        if (gravadas) {
            toast(`${gravadas.markers} marcador(es), ${gravadas.regions} região(ões) em "${gravadas.group}"`, "ok");
        }
    } catch (error) {
        state.analyzing = false;
        toast(error.message, "error");
        renderAnalysisResults();
    }
}

function analysisItemRow(item) {
    const tempo = item.start !== undefined ? item.start : item.time;
    const rotulo = item.start !== undefined
        ? `${fmtShort(item.start)} → ${fmtShort(item.end)}`
        : fmtShort(item.time);
    const score = item.score !== undefined ? `<span class="score">${Number(item.score).toFixed(1)}</span>` : "";
    return `<button type="button" class="analysis-item" data-analysis-jump="${Number(tempo)}">`
        + `<span class="time">${escapeHtml(rotulo)}</span>`
        + `<span class="label">${escapeHtml(item.label || "")}</span>${score}</button>`;
}

function renderAnalysisResults() {
    const box = $("#analysis-results");
    if (!box) return;
    if (state.analyzing) {
        box.innerHTML = '<div class="hint">Medindo com FFmpeg…</div>';
        return;
    }
    const analysis = state.analysis;
    const found = findClip(state.selectedClipId);
    if (!found || !analysis || analysis.clip_id !== found.clip.id) {
        box.innerHTML = '<div class="hint">Nada medido neste clipe.</div>';
        return;
    }
    const parts = [`<div class="analysis-summary">${escapeHtml(analysis.summary || "")}</div>`];
    if (analysis.kind === "loudness") {
        const m = analysis.measurements || {};
        parts.push('<div class="analysis-metrics">'
            + `<span><b>${m.integrated_lufs ?? "?"}</b> LUFS integrado</span>`
            + `<span><b>${m.lra_lu ?? "?"}</b> LU de range</span>`
            + `<span><b>${m.true_peak_dbfs ?? "?"}</b> dBFS de pico</span>`
            + "</div>");
        box.innerHTML = parts.join("");
        return;
    }
    const candidatos = analysis.candidates || [];
    parts.push(`<div class="analysis-list">${candidatos.slice(0, 40).map(analysisItemRow).join("")}</div>`);
    if (candidatos.length > 40) parts.push(`<div class="hint">+${candidatos.length - 40} candidatos</div>`);
    const grupo = analysis.group || "";
    const temGrupo = (state.project?.markers || []).some((m) => m.group === grupo)
        || (state.project?.regions || []).some((r) => r.group === grupo);
    parts.push('<div class="analysis-actions">'
        + `<button type="button" class="btn btn-small btn-primary" id="analysis-apply"${candidatos.length ? "" : " disabled"}>Aplicar como candidatos</button>`
        + (grupo
            ? `<button type="button" class="btn btn-small btn-ghost" id="analysis-clear"${temGrupo ? "" : " disabled"}>Limpar "${grupo}"</button>`
            : "")
        + "</div>");
    box.innerHTML = parts.join("");
}

function wireAnalysis(clip) {
    const seletor = $("#analysis-kind");
    seletor.value = state.analysisKind;
    seletor.addEventListener("change", () => {
        state.analysisKind = seletor.value;
        syncAnalysisFields();
    });
    $("#analysis-run").addEventListener("click", () => runAnalysis(clip));
    syncAnalysisFields();
    $("#analysis-results").addEventListener("click", (event) => {
        const jump = event.target.closest("[data-analysis-jump]");
        if (jump) {
            setPlayhead(Number(jump.dataset.analysisJump));
            return;
        }
        if (event.target.closest("#analysis-apply")) {
            runAnalysis(clip, { apply: true });
            return;
        }
        if (event.target.closest("#analysis-clear")) {
            const grupo = state.analysis?.group;
            if (!grupo) return;
            operation("clear_annotations", { group: grupo })
                .then(() => toast(`Anotações de "${grupo}" removidas`, "ok"))
                .catch((error) => toast(error.message, "error"));
        }
    });
    renderAnalysisResults();
}

/* -------------------------------------------------------------------- chat */

function activateRightTab(name) {
    $$(".right-tabs .tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${name}`));
}

function appendChatMessage(text, kind, { replace = null } = {}) {
    const container = $("#chat-messages");
    if (replace) {
        replace.textContent = text;
        container.scrollTop = container.scrollHeight;
        return replace;
    }
    const node = document.createElement("div");
    node.className = `msg ${kind}`;
    node.textContent = text;
    container.appendChild(node);
    container.scrollTop = container.scrollHeight;
    return node;
}

function appendAssistant(text) {
    const value = String(text || "").trim();
    if (!value) return;
    const messages = $$("#chat-messages .msg.assistant");
    const last = messages[messages.length - 1];
    if (last && last.textContent.trim() === value) return;
    appendChatMessage(value, "assistant");
}

function handleAgentEvent(event) {
    if (!event) return;
    if (state.turnId && event.turn_id && event.turn_id !== state.turnId) return;
    const loading = $("#chat-loading");
    if (event.kind === "tool_call") {
        appendChatMessage(`→ ${event.name || "ferramenta"} ${truncate(JSON.stringify(event.args || {}), 200)}`, "tool");
        activateRightTab("ai");
    } else if (event.kind === "tool_result") {
        appendChatMessage(`← ${event.name || "resultado"}: ${truncate(event.result || "", 260)}`, "tool result");
    } else if (event.kind === "text") {
        appendAssistant(event.text);
    } else if (event.kind === "answer") {
        state.answerShown = true;
        appendAssistant(event.text);
        if (event.duration) appendChatMessage(`turno: ${event.duration}s`, "tool");
        loading?.remove();
    } else if (event.kind === "loading") {
        const target = loading || appendChatMessage("", "loading");
        target.id = "chat-loading";
        target.textContent = `carregando modelo · ${event.progress ?? 0}%`;
    } else if (event.kind === "error") {
        appendChatMessage(event.text || "Erro", "error");
        loading?.remove();
    }
}

async function sendChat(event) {
    event.preventDefault();
    const input = $("#chat-input");
    const message = input.value.trim();
    if (!message || state.chatBusy) return;
    if (!state.projectId) {
        toast("Crie um projeto primeiro", "error");
        return;
    }
    input.value = "";
    appendChatMessage(message, "user");
    activateRightTab("ai");
    state.chatBusy = true;
    state.answerShown = false;
    state.turnId = `t_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`;
    state.turnProjectId = state.projectId;
    updateChatState();
    try {
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/chat`, {
            method: "POST",
            body: { message, turn_id: state.turnId },
        });
        if (!state.answerShown && data?.answer) {
            appendChatMessage(data.answer, data.error ? "error" : "assistant");
        }
        if (state.turnProjectId === state.projectId) {
            await refreshProject().catch(() => {});
            await loadJobs().catch(() => {});
        }
    } catch (error) {
        appendChatMessage(error.message, "error");
    } finally {
        $("#chat-loading")?.remove();
        state.chatBusy = false;
        state.turnId = null;
        state.turnProjectId = null;
        updateChatState();
    }
}

async function resetChat() {
    if (!state.projectId) return;
    try {
        await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/chat/reset`, { method: "POST" });
        $("#chat-messages").innerHTML = "";
        toast("Conversa reiniciada", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

/* ------------------------------------------------------------------ render */

async function loadJobs() {
    if (!state.projectId) return;
    try {
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/jobs`);
        setJobs(data.jobs || []);
    } catch {
        // silencioso: a lista se atualiza no próximo poll
    }
}

function setJobs(jobs, { notify = true } = {}) {
    const previous = new Map(state.jobs.map((job) => [job.id, job.status]));
    state.jobs = jobs || [];
    if (notify) {
        for (const job of state.jobs) {
            if (job.status === "done" && previous.has(job.id) && previous.get(job.id) !== "done") {
                toast(`Render concluído: ${job.output_name || job.id}`, "ok");
                if (job.output_name) setProgramSource(`/preview/${encodeURIComponent(job.output_name)}?v=${Date.now()}`, job.output_name, false);
                loadLatestPreview().catch(() => {});
            }
        }
    }
    renderJobs();
}

function jobStatusLabel(status) {
    return ({
        queued: "na fila", running: "renderizando", done: "concluído",
        error: "falhou", cancelled: "cancelado",
    }[status] || status || "—");
}

function renderJobs() {
    const list = $("#jobs-list");
    if (!state.projectId) {
        list.innerHTML = "";
        return;
    }
    if (!state.jobs.length) {
        list.innerHTML = '<div class="hint">Nenhuma renderização ainda.</div>';
        renderQC();
        ensurePolling();
        return;
    }
    list.innerHTML = state.jobs.map((job) => {
        const progress = clamp(Number(job.progress) || 0, 0, 100);
        const actions = [];
        if (job.status === "done" && job.output_name) {
            actions.push(`<button type="button" data-job-action="open" data-job="${escapeHtml(job.id)}">Abrir</button>`);
            actions.push(`<button type="button" data-job-action="validate" data-job="${escapeHtml(job.id)}">Revalidar</button>`);
            actions.push(`<a href="/download/${encodeURIComponent(job.output_name)}">Baixar</a>`);
        }
        if (["queued", "running"].includes(job.status)) {
            actions.push(`<button type="button" data-job-action="cancel" data-job="${escapeHtml(job.id)}">Cancelar</button>`);
        }
        const qcBadge = job.qc
            ? `<span class="job-status ${job.qc.ok ? "done" : "error"}">${job.qc.ok ? "QC ok" : "QC com erro"}</span>`
            : "";
        return `
            <div class="job-card">
                <div class="job-top">
                    <span class="job-kind">${job.kind === "preview" ? "prévia" : "export"}</span>
                    <span class="job-status ${escapeHtml(job.status)}">${escapeHtml(jobStatusLabel(job.status))}</span>
                    ${qcBadge}
                </div>
                <span class="job-name" title="${escapeHtml(job.output_name || "")}">${escapeHtml(job.output_name || job.id)}</span>
                ${job.status === "done" ? "" : `<div class="progress-bar"><span style="width:${progress}%"></span></div>`}
                <span class="job-name">${escapeHtml(job.message || "")}${["queued", "running"].includes(job.status) ? ` · ${progress}%` : ""}</span>
                ${job.error ? `<div class="job-error">${escapeHtml(job.error)}</div>` : ""}
                ${actions.length ? `<div class="job-actions">${actions.join("")}</div>` : ""}
            </div>`;
    }).join("");
    const active = state.jobs.some((job) => ["queued", "running"].includes(job.status));
    $("#job-dot").hidden = !active;
    renderQC();
    ensurePolling();
}

function renderQC() {
    const panel = $("#qc-panel");
    if (!state.jobs.length) {
        panel.className = "empty";
        panel.textContent = "Nenhum render concluído.";
        return;
    }
    const job = state.jobs.find((item) => item.id === state.openQcJobId && item.qc)
        || state.jobs.find((item) => item.qc);
    if (!job) {
        panel.className = "empty";
        panel.textContent = "Nenhum render concluído.";
        return;
    }
    const qc = job.qc;
    const measurements = qc.measurements || {};
    const rows = [];
    const add = (label, value) => rows.push(`<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`);
    if (measurements.duration !== undefined) add("Duração", fmtTime(measurements.duration, true));
    if (measurements.width !== undefined) add("Resolução", `${measurements.width}×${measurements.height}`);
    if (measurements.fps !== undefined) add("FPS", Number(measurements.fps).toFixed(3));
    if (measurements.size !== undefined) add("Tamanho", fmtBytes(measurements.size));
    if (measurements.has_audio !== undefined) add("Áudio", measurements.has_audio ? "sim" : "não");
    if (measurements.loudness_lufs !== undefined) add("Loudness", `${measurements.loudness_lufs} LUFS`);
    if (measurements.true_peak_dbfs !== undefined) add("Pico", `${measurements.true_peak_dbfs} dBFS`);
    if (measurements.lra_lu !== undefined) add("LRA", `${measurements.lra_lu} LU`);
    if (measurements.av_start_delta !== undefined) add("Delta A/V", `${measurements.av_start_delta} s`);
    if (measurements.black_ranges?.length) add("Faixas pretas", String(measurements.black_ranges.length));

    const issues = (qc.issues || []).map((issue) => `
        <div class="issue ${escapeHtml(issue.severity)}">
            <span class="issue-sev">${escapeHtml(issue.severity)}</span>
            <span>${escapeHtml(issue.message)}</span>
        </div>`).join("");

    panel.className = "issues-list";
    panel.innerHTML = `
        <div class="job-top">
            <span class="job-kind">${job.kind === "preview" ? "prévia" : "export"}</span>
            <span class="job-name" title="${escapeHtml(job.output_name || "")}">${escapeHtml(job.output_name || "")}</span>
            <span class="job-status ${qc.ok ? "done" : "error"}">${qc.ok ? "QC ok" : "QC com erro"}</span>
        </div>
        <dl class="qc-measurements">${rows.join("")}</dl>
        ${issues || '<div class="hint">Nenhum problema detectado.</div>'}`;
}

function ensurePolling() {
    const active = state.jobs.some((job) => ["queued", "running"].includes(job.status));
    if (active && !state.pollTimer) {
        state.pollTimer = setInterval(async () => {
            if (!state.projectId) return;
            try {
                const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/jobs`);
                setJobs(data.jobs || []);
            } catch {
                // mantém o poll
            }
        }, 1200);
    } else if (!active && state.pollTimer) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
    }
}

async function submitRender(preview) {
    if (!state.projectId) {
        toast("Crie um projeto primeiro", "error");
        return;
    }
    const button = preview ? $("#preview-btn") : $("#export-btn");
    button.disabled = true;
    try {
        const options = preview
            ? { preview: true, format: "mp4" }
            : {
                preview: false,
                format: $("#export-format").value,
                crf: Number($("#export-crf").value || 20),
                filename: $("#export-name").value.trim() || undefined,
            };
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/render`, {
            method: "POST",
            body: options,
        });
        state.jobs = [data.job, ...state.jobs.filter((job) => job.id !== data.job.id)];
        renderJobs();
        activateRightTab("output");
        toast("Renderização iniciada", "ok");
    } catch (error) {
        toast(error.message, "error");
    } finally {
        button.disabled = false;
    }
}

async function handleJobAction(action, jobId) {
    const job = state.jobs.find((item) => item.id === jobId);
    if (!job) return;
    if (action === "open") {
        setProgramSource(`/preview/${encodeURIComponent(job.output_name)}?v=${Date.now()}`, job.output_name);
        return;
    }
    if (action === "cancel") {
        try {
            const data = await api(`/api/editor/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
            state.jobs = state.jobs.map((item) => item.id === jobId ? data.job || data : item);
            renderJobs();
        } catch (error) {
            toast(error.message, "error");
        }
        return;
    }
    if (action === "validate") {
        try {
            const data = await api(`/api/editor/jobs/${encodeURIComponent(jobId)}/validate`, { method: "POST" });
            state.jobs = state.jobs.map((item) => item.id === jobId ? { ...item, qc: data.qc } : item);
            state.openQcJobId = jobId;
            renderJobs();
            activateRightTab("output");
            toast(data.qc?.ok ? "QC ok" : "QC encontrou problemas", data.qc?.ok ? "ok" : "error");
        } catch (error) {
            toast(error.message, "error");
        }
    }
}

/* ----------------------------------------------------------------- monitor */

function setProgramSource(url, label, switchTab = true) {
    const video = $("#program-video");
    stopVirtual();
    video.src = url;
    video.hidden = false;
    state.programLabel = label || "";
    if (switchTab) activateMonitor("program");
    updateMonitor();
    try {
        video.load();
    } catch {
        // sem src válido
    }
}

function stopProgram() {
    const video = $("#program-video");
    try {
        video.pause();
    } catch {
        // ignorado
    }
    video.removeAttribute("src");
    video.load();
    state.programLabel = "";
}

async function loadLatestPreview() {
    if (!state.projectId) return;
    try {
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/preview`);
        if (data?.job?.output_name) {
            setProgramSource(
                `/preview/${encodeURIComponent(data.job.output_name)}?v=${Date.now()}`,
                data.job.output_name,
                false,
            );
        }
    } catch {
        // sem prévia
    }
}

function activateMonitor(name) {
    state.monitor = name;
    if (name === "source") {
        try { $("#program-video").pause(); } catch { /* ignorado */ }
    } else {
        try { $("#source-video").pause(); } catch { /* ignorado */ }
    }
    updateMonitor();
}

function updateMonitor() {
    const program = state.monitor === "program";
    const programVideo = $("#program-video");
    const sourceVideo = $("#source-video");
    const hasProgram = Boolean(programVideo.getAttribute("src"));
    const hasSource = Boolean(sourceVideo.getAttribute("src"));
    programVideo.hidden = !(program && hasProgram);
    sourceVideo.hidden = !(!program && hasSource);
    const empty = $("#monitor-empty");
    empty.hidden = program ? hasProgram : hasSource;
    empty.querySelector("span").textContent = program ? "Sem prévia renderizada" : "Selecione uma mídia";
    $("#render-preview-empty").hidden = !program || !state.projectId;
    $("#monitor-label").textContent = program ? (state.programLabel || "") : (state.sourceLabel || "");
    $$("[data-monitor]").forEach((tab) => tab.classList.toggle("active", tab.dataset.monitor === state.monitor));
    updatePlayButton();
}

function updatePlayButton() {
    const button = $("#play-btn");
    if (state.monitor === "program" && $("#program-video").getAttribute("src")) {
        button.textContent = $("#program-video").paused ? "▶" : "❙❙";
    } else {
        button.textContent = state.virtualRaf ? "❙❙" : "▶";
    }
}

function togglePlay() {
    if (state.monitor === "program" && $("#program-video").getAttribute("src")) {
        const video = $("#program-video");
        if (video.paused) video.play().catch(() => toast("Não foi possível reproduzir a prévia", "error"));
        else video.pause();
        return;
    }
    if (state.virtualRaf) stopVirtual();
    else startVirtual();
}

function startVirtual() {
    if (!state.project || projectDuration() <= 0) return;
    if (state.playhead >= projectDuration() - 0.02) setPlayhead(0);
    const base = state.playhead;
    const started = performance.now();
    const step = (now) => {
        const next = base + (now - started) / 1000;
        if (next >= projectDuration()) {
            setPlayhead(projectDuration(), { seek: false });
            stopVirtual();
            return;
        }
        setPlayhead(next, { seek: false });
        state.virtualRaf = requestAnimationFrame(step);
    };
    state.virtualRaf = requestAnimationFrame(step);
    updatePlayButton();
}

function stopVirtual() {
    if (state.virtualRaf) cancelAnimationFrame(state.virtualRaf);
    state.virtualRaf = null;
    updatePlayButton();
}

/* ---------------------------------------------------------------- painéis */

function renderIssues() {
    const list = $("#issues-list");
    const issues = state.issues || [];
    if (!state.project) {
        list.innerHTML = "";
        return;
    }
    if (!issues.length) {
        list.innerHTML = '<div class="hint">Nenhum problema encontrado.</div>';
        return;
    }
    list.innerHTML = issues.map((issue) => {
        const clip = issue.clip_id ? ` data-clip="${escapeHtml(issue.clip_id)}"` : "";
        return `<button type="button" class="issue ${escapeHtml(issue.severity)}"${clip}>
            <span class="issue-sev">${escapeHtml(issue.severity)}</span>
            <span>${escapeHtml(issue.message)}</span>
        </button>`;
    }).join("");
}

function renderMarkersPanel() {
    const list = $("#markers-list");
    const markers = state.project?.markers || [];
    if (!markers.length) {
        list.innerHTML = '<div class="hint">Nenhum marcador.</div>';
        return;
    }
    list.innerHTML = markers.map((marker) => `
        <div class="marker-row">
            <span class="time">${fmtTime(marker.time)}</span>
            <button type="button" class="link" data-marker-jump="${marker.time}">${escapeHtml(marker.label || "Marcador")}</button>
            <button type="button" class="remove" data-marker-remove="${escapeHtml(marker.id)}">remover</button>
        </div>`).join("");
}

function renderRegionsPanel() {
    const list = $("#regions-list");
    const regions = state.project?.regions || [];
    if (!regions.length) {
        list.innerHTML = '<div class="hint">Nenhuma região.</div>';
        return;
    }
    list.innerHTML = regions.map((region) => `
        <div class="marker-row">
            <span class="time">${fmtTime(region.start)} → ${fmtTime(region.end)}</span>
            <button type="button" class="link" data-region-jump="${Number(region.start)}">${escapeHtml(region.label || "Região")}</button>
            <button type="button" class="remove" data-region-remove="${escapeHtml(region.id)}">remover</button>
        </div>`).join("");
}

async function loadVersions() {
    if (!state.projectId) return;
    try {
        const data = await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}/versions`);
        state.versions = data.versions || [];
        renderVersions();
    } catch {
        state.versions = [];
        renderVersions();
    }
}

function renderVersions() {
    const list = $("#versions-list");
    if (!state.project) {
        list.innerHTML = "";
        return;
    }
    if (!state.versions.length) {
        list.innerHTML = '<div class="hint">Nenhuma versão salva.</div>';
        return;
    }
    list.innerHTML = state.versions.slice(0, 12).map((version) => {
        const date = new Date((version.modified || 0) * 1000);
        const when = Number.isNaN(date.getTime())
            ? ""
            : `${pad(date.getDate())}/${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
        return `
            <div class="version-row">
                <span class="time">${when}</span>
                <button type="button" class="link" title="${escapeHtml(version.name)}">${escapeHtml(version.label || "versão")}</button>
                <button type="button" class="restore" data-version="${escapeHtml(version.name)}">restaurar</button>
            </div>`;
    }).join("");
}

function renderHistory() {
    const list = $("#history-list");
    const undo = state.history?.undo || [];
    const redo = state.history?.redo || [];
    if (!state.project) {
        list.innerHTML = "";
        return;
    }
    if (!undo.length && !redo.length) {
        list.innerHTML = '<div class="hint">Nenhuma operação ainda.</div>';
        return;
    }
    const rows = [];
    for (const label of undo.slice(0, 8)) rows.push(`<div class="history-row"><span>${escapeHtml(label)}</span><span>desfazer</span></div>`);
    for (const label of redo.slice(0, 8)) rows.push(`<div class="history-row"><span>${escapeHtml(label)}</span><span>refazer</span></div>`);
    list.innerHTML = rows.join("");
}

async function saveSettings(event) {
    event.preventDefault();
    if (!state.projectId) return;
    const name = $("#ps-name").value.trim();
    const width = num($("#ps-width").value);
    const height = num($("#ps-height").value);
    const fps = num($("#ps-fps").value);
    if (!name || !width || !height || !fps) {
        toast("Preencha nome, largura, altura e fps", "error");
        return;
    }
    try {
        await operation("settings", { name, width, height, fps });
        toast("Configurações atualizadas", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function deleteProject() {
    if (!state.projectId) return;
    const confirmed = await confirmDialog(
        "Excluir projeto",
        `Mover "${state.project?.name || state.projectId}" para a lixeira? O projeto sai da interface, mas a pasta é preservada em projects/.trash.`,
        "Excluir projeto",
    );
    if (!confirmed) return;
    try {
        await api(`/api/editor/projects/${encodeURIComponent(state.projectId)}?confirm=true`, { method: "DELETE" });
        state.projectId = null;
        state.project = null;
        clearProject();
        await loadProjects();
        toast("Projeto excluído", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

async function restoreVersion(name) {
    if (!state.projectId) return;
    const confirmed = await confirmDialog("Restaurar versão", "Substituir a timeline atual por esta versão? A alteração entra no histórico.", "Restaurar");
    if (!confirmed) return;
    try {
        applyPayload(await api(
            `/api/editor/projects/${encodeURIComponent(state.projectId)}/versions/${encodeURIComponent(name)}/restore`,
            { method: "POST" },
        ));
        await loadVersions();
        toast("Versão restaurada", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

/* --------------------------------------------------------------- diálogos */

function confirmDialog(title, message, confirmLabel = "Confirmar") {
    return new Promise((resolve) => {
        const dialog = $("#confirm-dialog");
        $("#confirm-title").textContent = title;
        $("#confirm-message").textContent = message;
        $("#confirm-ok").textContent = confirmLabel;
        dialog.returnValue = "cancel";
        const onClose = () => {
            dialog.removeEventListener("close", onClose);
            resolve(dialog.returnValue === "ok");
        };
        dialog.addEventListener("close", onClose);
        if (dialog.open) dialog.close();
        dialog.showModal();
    });
}

function openProjectDialog() {
    $("#project-form").reset();
    $("#np-name").value = "Meu vídeo";
    $("#np-preset").value = "1920x1080@30";
    $("#np-width").value = 1920;
    $("#np-height").value = 1080;
    $("#np-fps").value = 30;
    const dialog = $("#project-dialog");
    if (!dialog.open) dialog.showModal();
    setTimeout(() => $("#np-name").focus(), 50);
}

async function createProject(event) {
    event.preventDefault();
    const name = $("#np-name").value.trim();
    const width = Number($("#np-width").value);
    const height = Number($("#np-height").value);
    const fps = Number($("#np-fps").value);
    if (!name) {
        toast("Informe o nome do projeto", "error");
        return;
    }
    try {
        const data = await api("/api/editor/projects", {
            method: "POST",
            body: { name, width, height, fps },
        });
        $("#project-dialog").close();
        state.projectId = data.project.id;
        applyPayload(data);
        await Promise.allSettled([loadVersions(), loadJobs(), loadLatestPreview()]);
        await refreshProjects();
        toast("Projeto criado", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

function openTitleDialog() {
    if (!state.projectId) {
        toast("Crie um projeto primeiro", "error");
        return;
    }
    $("#title-form").reset();
    $("#title-text").value = "";
    $("#title-start").value = Number(state.playhead.toFixed(2));
    $("#title-duration").value = 3;
    $("#title-size").value = 56;
    $("#title-position").value = "inferior";
    $("#title-color").value = "#ffffff";
    $("#title-background").checked = true;
    const dialog = $("#title-dialog");
    if (!dialog.open) dialog.showModal();
    setTimeout(() => $("#title-text").focus(), 50);
}

async function createTitle(event) {
    event.preventDefault();
    const text = $("#title-text").value.trim();
    if (!text) {
        toast("Informe o texto do título", "error");
        return;
    }
    try {
        await operation("add_text", {
            text,
            start: Number($("#title-start").value || 0),
            duration: Number($("#title-duration").value || 3),
            font_size: Number($("#title-size").value || 56),
            position: $("#title-position").value,
            color: $("#title-color").value,
            background: $("#title-background").checked,
        });
        $("#title-dialog").close();
        toast("Título adicionado", "ok");
    } catch (error) {
        toast(error.message, "error");
    }
}

/* ----------------------------------------------------------------- eventos */

function bindEvents() {
    $("#project-select").addEventListener("change", (event) => {
        if (event.target.value) openProject(event.target.value, true);
    });
    $("#new-project-btn").addEventListener("click", openProjectDialog);
    $("#np-cancel").addEventListener("click", () => $("#project-dialog").close());
    $("#project-form").addEventListener("submit", createProject);
    $("#np-preset").addEventListener("change", (event) => {
        const value = event.target.value;
        if (value === "custom") {
            $("#np-width").focus();
            return;
        }
        const [size, fps] = value.split("@");
        const [width, height] = size.split("x");
        $("#np-width").value = width;
        $("#np-height").value = height;
        $("#np-fps").value = fps;
    });

    $("#ai-status").addEventListener("click", loadStatus);
    $("#toggle-media").addEventListener("click", () => $("#media-panel").classList.toggle("open"));

    $("#upload-media-btn").addEventListener("click", () => $("#upload-media-input").click());
    $("#upload-media-input").addEventListener("change", async (event) => {
        const files = event.target.files;
        $("#upload-media-btn").disabled = true;
        try {
            await uploadFiles(files);
        } finally {
            $("#upload-media-btn").disabled = false;
            event.target.value = "";
        }
    });
    $("#local-add-btn").addEventListener("click", () => {
        const input = $("#local-path-input");
        const path = input.value.trim().replace(/^["']|["']$/g, "");
        if (!path) return;
        addMedia(path, isAudioPath(path) ? "a1" : "v1");
        input.value = "";
    });
    $("#local-path-input").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            $("#local-add-btn").click();
        }
    });
    $("#media-list").addEventListener("click", (event) => {
        const add = event.target.closest("[data-add-track]");
        if (add) {
            addMedia(add.dataset.path, add.dataset.addTrack);
            return;
        }
        const source = event.target.closest("[data-source]");
        if (source) selectSource(source.dataset.source);
    });
    $("#add-title-btn").addEventListener("click", openTitleDialog);
    $("#upload-subtitle-btn").addEventListener("click", () => $("#subtitle-input").click());
    $("#subtitle-input").addEventListener("change", async (event) => {
        const file = event.target.files?.[0];
        if (file) await uploadFiles([file], true);
        event.target.value = "";
    });
    $("#title-cancel").addEventListener("click", () => $("#title-dialog").close());
    $("#title-form").addEventListener("submit", createTitle);
    $("#skills-list").addEventListener("click", (event) => {
        const button = event.target.closest("[data-skill]");
        if (button) openSkill(button.dataset.skill);
    });

    $$("[data-monitor]").forEach((tab) => tab.addEventListener("click", () => activateMonitor(tab.dataset.monitor)));
    $("#play-btn").addEventListener("click", togglePlay);
    $("#render-preview-empty").addEventListener("click", () => submitRender(true));
    $("#snap-toggle").addEventListener("change", (event) => {
        state.snap = event.target.checked;
        renderTimeline();
    });
    $("#zoom-range").addEventListener("input", (event) => {
        state.pps = Number(event.target.value);
        renderTimeline();
    });
    $("#zoom-in").addEventListener("click", () => {
        state.pps = clamp(state.pps + 20, 20, 300);
        $("#zoom-range").value = state.pps;
        renderTimeline();
    });
    $("#zoom-out").addEventListener("click", () => {
        state.pps = clamp(state.pps - 20, 20, 300);
        $("#zoom-range").value = state.pps;
        renderTimeline();
    });
    $("#zoom-fit").addEventListener("click", () => {
        const width = $("#timeline-scroll").clientWidth - HEADER_W - 60;
        state.pps = clamp(width / Math.max(1, projectDuration()), 20, 300);
        $("#zoom-range").value = state.pps;
        renderTimeline();
        $("#timeline-scroll").scrollLeft = 0;
    });

    $("#undo-btn").addEventListener("click", undo);
    $("#redo-btn").addEventListener("click", redo);
    $("#split-btn").addEventListener("click", splitAtPlayhead);
    $("#duplicate-btn").addEventListener("click", duplicateSelected);
    $("#delete-btn").addEventListener("click", deleteSelected);
    $("#marker-btn").addEventListener("click", addMarker);
    $("#mark-in-btn").addEventListener("click", () => markRegion("markIn"));
    $("#mark-out-btn").addEventListener("click", () => markRegion("markOut"));
    $("#region-btn").addEventListener("click", addRegion);
    $("#marker-label").addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            addMarker();
        }
    });
    $("#timeline-content").addEventListener("pointerdown", onTimelinePointerDown);

    $$(".right-tabs .tab").forEach((tab) => tab.addEventListener("click", () => activateRightTab(tab.dataset.tab)));
    $("#chat-form").addEventListener("submit", sendChat);
    $("#chat-reset").addEventListener("click", resetChat);

    $("#preview-btn").addEventListener("click", () => submitRender(true));
    $("#export-btn").addEventListener("click", () => submitRender(false));
    $("#jobs-list").addEventListener("click", (event) => {
        const action = event.target.closest("[data-job-action]");
        if (action) handleJobAction(action.dataset.jobAction, action.dataset.job);
    });
    $("#qc-panel").addEventListener("click", (event) => {
        const action = event.target.closest("[data-job-action]");
        if (action) handleJobAction(action.dataset.jobAction, action.dataset.job);
    });

    $("#settings-form").addEventListener("submit", saveSettings);
    $("#delete-project-btn").addEventListener("click", deleteProject);
    $("#issues-list").addEventListener("click", (event) => {
        const item = event.target.closest("[data-clip]");
        if (!item) return;
        const found = findClip(item.dataset.clip);
        if (!found) return;
        setPlayhead(found.clip.start);
        selectClip(found.clip.id);
    });
    $("#markers-list").addEventListener("click", (event) => {
        const remove = event.target.closest("[data-marker-remove]");
        if (remove) {
            operation("remove_marker", { marker_id: remove.dataset.markerRemove }).catch((error) => toast(error.message, "error"));
            return;
        }
        const jump = event.target.closest("[data-marker-jump]");
        if (jump) setPlayhead(Number(jump.dataset.markerJump));
    });
    $("#regions-list").addEventListener("click", (event) => {
        const remove = event.target.closest("[data-region-remove]");
        if (remove) {
            operation("remove_region", { region_id: remove.dataset.regionRemove }).catch((error) => toast(error.message, "error"));
            return;
        }
        const jump = event.target.closest("[data-region-jump]");
        if (jump) setPlayhead(Number(jump.dataset.regionJump));
    });
    $("#versions-list").addEventListener("click", (event) => {
        const restore = event.target.closest("[data-version]");
        if (restore) restoreVersion(restore.dataset.version);
    });

    const programVideo = $("#program-video");
    programVideo.addEventListener("timeupdate", () => {
        if (state.monitor === "program") setPlayhead(programVideo.currentTime, { seek: false });
    });
    programVideo.addEventListener("loadedmetadata", () => {
        if (state.playhead > 0) seekProgram(state.playhead);
    });
    programVideo.addEventListener("play", () => { stopVirtual(); updatePlayButton(); });
    programVideo.addEventListener("pause", updatePlayButton);
    programVideo.addEventListener("ended", updatePlayButton);

    document.addEventListener("keydown", (event) => {
        const target = event.target;
        const typing = target instanceof HTMLElement
            && (["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) || target.isContentEditable);
        if (typing) return;
        const key = event.key.toLowerCase();
        if (event.code === "Space") {
            event.preventDefault();
            togglePlay();
        } else if ((event.ctrlKey || event.metaKey) && key === "z") {
            event.preventDefault();
            if (event.shiftKey) redo(); else undo();
        } else if ((event.ctrlKey || event.metaKey) && key === "y") {
            event.preventDefault();
            redo();
        } else if (event.key === "Delete" || event.key === "Backspace") {
            event.preventDefault();
            deleteSelected();
        } else if (key === "s") {
            event.preventDefault();
            splitAtPlayhead();
        } else if (key === "m") {
            event.preventDefault();
            addMarker();
        } else if (key === "i") {
            event.preventDefault();
            markRegion("markIn");
        } else if (key === "o") {
            event.preventDefault();
            markRegion("markOut");
        } else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            const frame = 1 / Math.max(1, Number(state.project?.settings?.fps) || 30);
            const step = event.shiftKey ? 1 : frame;
            setPlayhead(state.playhead + (event.key === "ArrowRight" ? step : -step));
        }
    });

    let resizeTimer = null;
    window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
            if (state.project) renderTimeline();
        }, 160);
    });
}

async function init() {
    bindEvents();
    connectWS();
    loadStatus();
    await Promise.allSettled([loadSkills(), loadUploads()]);
    try {
        await loadProjects();
    } catch (error) {
        toast(error.message, "error");
        clearProject();
    }
    setInterval(loadStatus, 90000);
}

document.addEventListener("DOMContentLoaded", init);
