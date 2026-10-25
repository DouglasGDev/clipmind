// ClipMind - interface do editor
let currentVideoPath = null;
let currentVideoName = "";
let videoPlayer = null;
let ws = null;
let tools = [];
let selectedTool = null;
let knownOutputs = new Set();
let resultsFirstLoad = true;
let refreshTimer = null;
let myTurnId = null;
let allOutputs = [];
let resultsLimit = 12;

const $ = (id) => document.getElementById(id);

document.addEventListener('DOMContentLoaded', () => {
    videoPlayer = $('video-player');
    setupDragDrop();
    setupVideoInput();
    setupChat();
    setupTimeline();
    setupButtons();
    setupWebSocket();
    checkAgentStatus();
    loadTools();
    refreshResults();
});

// ---------------------------------------------------------------- WebSocket

function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch {
            return;
        }
        handleWebSocketMessage(data);
    };

    ws.onclose = () => {
        setTimeout(setupWebSocket, 3000);
    };
}

function handleWebSocketMessage(data) {
    if (data.type === 'processing') {
        showProgress(data.action);
    } else if (data.type === 'complete') {
        hideProgress();
    } else if (data.type === 'chat_reset') {
        clearChat();
    } else if (data.type === 'agent') {
        handleAgentEvent(data);
    }
}

function handleAgentEvent(event) {
    const isMine = Boolean(myTurnId) && event.turn_id === myTurnId;

    switch (event.kind) {
        case 'tool_call':
            addChatMessage('tool', `▸ ${event.name}${summarizeArgs(event.args)}`);
            showProgress(`${event.name}...`);
            break;
        case 'tool_result': {
            const text = String(event.result || '').trim();
            const short = text.length > 220 ? `${text.slice(0, 220)}…` : text;
            addChatMessage('tool', `✓ ${event.name || 'ferramenta'}${short ? ` · ${short}` : ''}`);
            hideProgress();
            if (/salv[oa] em:/i.test(text)) scheduleResultsRefresh();
            break;
        }
        case 'loading':
            showProgress(`Carregando modelo… ${event.progress}%`);
            break;
        case 'error':
            hideProgress();
            // O pedido que originou o erro recebe o texto na resposta HTTP.
            if (!isMine) addChatMessage('assistant error', event.text);
            break;
        case 'answer':
            hideProgress();
            if (!isMine && event.text) addChatMessage('assistant', event.text);
            break;
    }
}

function summarizeArgs(args) {
    if (!args || typeof args !== 'object') return '';
    const parts = [];
    if (args.video_path) parts.push(baseName(args.video_path));
    if (args.video_paths) parts.push(baseName(String(args.video_paths).split(',')[0]) + '…');
    if (args.start) parts.push(`de ${args.start}`);
    if (args.end) parts.push(`até ${args.end}`);
    if (args.duration) parts.push(`${args.duration}s`);
    if (args.segments) parts.push(String(args.segments));
    if (args.text) parts.push(`“${String(args.text).slice(0, 40)}”`);
    if (args.format) parts.push(String(args.format));
    return parts.length ? ` · ${parts.join(' ')}` : '';
}

// ---------------------------------------------------------------- Upload

function setupDragDrop() {
    const area = $('upload-area');

    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        area.classList.add('dragging');
    });

    area.addEventListener('dragleave', () => area.classList.remove('dragging'));

    area.addEventListener('drop', (e) => {
        e.preventDefault();
        area.classList.remove('dragging');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('video/')) handleVideoFile(file);
    });
}

function setupVideoInput() {
    $('btn-pick-video').addEventListener('click', () => $('video-input').click());
    $('btn-change-video').addEventListener('click', () => $('video-input').click());
    $('video-input').addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) handleVideoFile(file);
        e.target.value = '';
    });
}

async function handleVideoFile(file) {
    showProgress('Enviando vídeo...');
    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/upload', { method: 'POST', body: formData });
        if (!response.ok) throw new Error(`servidor respondeu ${response.status}`);
        const data = await response.json();

        currentVideoPath = data.file_path;
        currentVideoName = data.name || file.name;
        showVideo(URL.createObjectURL(file), currentVideoName);
        addChatMessage('assistant', `Vídeo carregado: ${currentVideoName}`);
    } catch (error) {
        addChatMessage('assistant error', `Falha ao enviar o vídeo: ${error.message}`);
    } finally {
        hideProgress();
    }
}

function showVideo(url, name) {
    videoPlayer.src = url;
    videoPlayer.load();
    $('video-name').textContent = name;
    $('upload-area').hidden = true;
    $('video-preview').hidden = false;
    $('timeline').hidden = false;
    updateTimelineMeta();
    loadVideoInfo();
}

function useVideoFile(path, url, name) {
    currentVideoPath = path;
    currentVideoName = name;
    showVideo(url, name);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// ---------------------------------------------------------------- Timeline

function setupTimeline() {
    $('timeline-bar').addEventListener('click', (e) => {
        if (!videoPlayer.duration) return;
        const rect = e.currentTarget.getBoundingClientRect();
        const percent = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
        videoPlayer.currentTime = percent * videoPlayer.duration;
        updateTimelineMeta();
    });

    videoPlayer.addEventListener('timeupdate', updateTimelineMeta);
    videoPlayer.addEventListener('loadedmetadata', updateTimelineMeta);
}

function updateTimelineMeta() {
    const duration = videoPlayer.duration;
    if (!duration || Number.isNaN(duration)) return;

    const current = videoPlayer.currentTime || 0;
    $('timeline-progress').style.width = `${(current / duration) * 100}%`;
    $('current-time').textContent = formatTime(current);
    $('total-time').textContent = formatTime(duration);
}

function setCutPoint(type) {
    if (!videoPlayer.duration) {
        addChatMessage('assistant', 'Carregue um vídeo para marcar os pontos de corte.');
        return;
    }
    const input = $(type === 'start' ? 'cut-start' : 'cut-end');
    input.value = formatTime(videoPlayer.currentTime);
}

function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function baseName(path) {
    return String(path).split(/[\\/]/).pop() || String(path);
}

// ---------------------------------------------------------------- Informações

let infoSeq = 0;

async function loadVideoInfo() {
    const seq = ++infoSeq;
    const card = $('video-info-card');
    if (!currentVideoPath) {
        card.hidden = true;
        return;
    }

    try {
        const response = await fetch(`/media-info?path=${encodeURIComponent(currentVideoPath)}`);
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (seq !== infoSeq) return;

        const streams = data.streams || [];
        const video = streams.find((s) => s.tipo === 'video') || {};
        const audio = streams.find((s) => s.tipo === 'audio') || {};
        const [num, den] = String(video.fps || '').split('/');
        const fps = Number(den) ? `${(Number(num) / Number(den)).toFixed(2).replace(/\.00$/, '')} fps` : (video.fps || '—');

        const rows = [
            ['Duração', data.duracao_formato || '—'],
            ['Resolução', video.resolucao || '—'],
            ['FPS', fps],
            ['Vídeo', video.codec || '—'],
            ['Áudio', audio.codec || 'sem áudio'],
            ['Tamanho', data.tamanho_bytes ? formatSize(data.tamanho_bytes) : '—'],
        ];

        const list = $('video-info');
        list.textContent = '';
        for (const [label, value] of rows) {
            const term = document.createElement('dt');
            term.textContent = label;
            const detail = document.createElement('dd');
            detail.textContent = value;
            list.append(term, detail);
        }
        card.hidden = false;
    } catch {
        if (seq === infoSeq) card.hidden = true;
    }
}

// ---------------------------------------------------------------- Ferramentas

async function loadTools() {
    try {
        const response = await fetch('/tools');
        tools = await response.json();
        renderToolList();
        $('tool-count').textContent = `${tools.length} ferramentas`;
    } catch (error) {
        $('tool-list').textContent = 'Não foi possível carregar as ferramentas.';
    }
}

function renderToolList() {
    const list = $('tool-list');
    list.textContent = '';

    const groups = new Map();
    for (const tool of tools) {
        if (!groups.has(tool.group)) groups.set(tool.group, []);
        groups.get(tool.group).push(tool);
    }

    for (const [group, items] of groups) {
        const section = document.createElement('div');
        section.className = 'tool-group';

        const title = document.createElement('h3');
        title.textContent = group;
        section.appendChild(title);

        const grid = document.createElement('div');
        grid.className = 'tool-grid';

        for (const tool of items) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'tool-btn';
            button.dataset.tool = tool.name;
            button.disabled = !tool.available;

            const icon = document.createElement('span');
            icon.className = 'tool-icon';
            icon.textContent = tool.icon || '🛠️';
            const label = document.createElement('span');
            label.className = 'tool-label';
            label.textContent = tool.label;

            button.append(icon, label);
            button.addEventListener('click', () => openTool(tool.name));
            grid.appendChild(button);
        }

        section.appendChild(grid);
        list.appendChild(section);
    }
}

function openTool(name) {
    const tool = tools.find((item) => item.name === name);
    if (!tool) return;

    selectedTool = tool;
    document.querySelectorAll('.tool-btn').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.tool === name);
    });

    $('tool-form-card').hidden = false;
    $('tool-form-title').textContent = `${tool.icon || ''} ${tool.label}`.trim();
    $('tool-result').hidden = true;
    $('tool-result').textContent = '';

    const form = $('tool-form');
    form.textContent = '';
    for (const field of tool.fields) {
        form.appendChild(buildField(field));
    }

    const actions = document.createElement('div');
    actions.className = 'form-actions';
    const submit = document.createElement('button');
    submit.type = 'submit';
    submit.className = 'btn btn-primary';
    submit.textContent = 'Executar';
    actions.appendChild(submit);
    form.appendChild(actions);

    form.onsubmit = (event) => {
        event.preventDefault();
        runSelectedTool(submit);
    };

    $('tool-form-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function buildField(field) {
    const wrapper = document.createElement('div');
    wrapper.className = 'field';

    const label = document.createElement('label');
    label.textContent = field.label || field.name;
    label.htmlFor = `field-${field.name}`;
    wrapper.appendChild(label);

    const row = document.createElement('div');
    row.className = 'field-row';

    let input;
    if (field.type === 'select') {
        input = document.createElement('select');
        for (const option of field.options || []) {
            const opt = document.createElement('option');
            opt.value = option;
            opt.textContent = option;
            input.appendChild(opt);
        }
        if (field.default) input.value = field.default;
    } else {
        input = document.createElement('input');
        input.type = 'text';
        input.autocomplete = 'off';
        if (field.placeholder) input.placeholder = field.placeholder;
        if (field.default) input.value = field.default;
        if (field.type === 'video' && currentVideoPath) {
            input.value = currentVideoPath;
        }
    }
    input.id = `field-${field.name}`;
    input.name = field.name;
    input.dataset.fieldType = field.type || 'text';
    row.appendChild(input);

    if (field.type === 'video') {
        row.appendChild(pathButton('Usar atual', () => {
            if (!currentVideoPath) {
                toast('Nenhum vídeo carregado.');
                return;
            }
            input.value = currentVideoPath;
        }));
        row.appendChild(pathButton('Escolher', () => pickAndUpload(input, 'video/*', true)));
    } else if (field.name === 'music_path') {
        row.appendChild(pathButton('Enviar', () => pickAndUpload(input, 'audio/*', false)));
    } else if (field.name === 'subtitle_path') {
        row.appendChild(pathButton('Enviar', () => pickAndUpload(input, '.srt,.ass,.vtt', false)));
    } else if (field.name === 'video_paths') {
        row.appendChild(pathButton('Adicionar', async () => {
            const path = await pickAndUpload(input, 'video/*', false, true);
            if (!path) return;
            const current = input.value.trim();
            input.value = current ? `${current}, ${path}` : path;
        }));
    }

    wrapper.appendChild(row);
    return wrapper;
}

function pathButton(text, onClick) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-small btn-ghost';
    button.textContent = text;
    button.addEventListener('click', onClick);
    return button;
}

function pickAndUpload(input, accept, makeCurrent, returnOnly = false) {
    return new Promise((resolve) => {
        const picker = document.createElement('input');
        picker.type = 'file';
        picker.accept = accept;
        picker.hidden = true;
        document.body.appendChild(picker);

        picker.addEventListener('change', async () => {
            const file = picker.files[0];
            picker.remove();
            if (!file) {
                resolve(null);
                return;
            }
            showProgress('Enviando arquivo...');
            try {
                const body = new FormData();
                body.append('file', file);
                const response = await fetch('/upload', { method: 'POST', body });
                if (!response.ok) throw new Error(`servidor respondeu ${response.status}`);
                const data = await response.json();
                if (makeCurrent) {
                    currentVideoPath = data.file_path;
                    currentVideoName = data.name || file.name;
                    showVideo(URL.createObjectURL(file), currentVideoName);
                }
                if (!returnOnly) input.value = data.file_path;
                resolve(data.file_path);
            } catch (error) {
                toast(`Falha no envio: ${error.message}`);
                resolve(null);
            } finally {
                hideProgress();
            }
        }, { once: true });

        picker.click();
    });
}

async function runSelectedTool(submitButton) {
    if (!selectedTool) return;
    const form = $('tool-form');
    const payload = {};
    for (const element of form.elements) {
        if (!element.name) continue;
        const value = element.value.trim();
        if (value) payload[element.name] = value;
    }

    submitButton.disabled = true;
    showProgress(`${selectedTool.label}...`);

    try {
        const response = await fetch(`/tool/${encodeURIComponent(selectedTool.name)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(data.detail || `servidor respondeu ${response.status}`);
        }

        showToolResult(data);
        if (data.output_name) scheduleResultsRefresh();
    } catch (error) {
        showToolResult({ ok: false, result: error.message });
    } finally {
        submitButton.disabled = false;
        hideProgress();
    }
}

function showToolResult(data) {
    const box = $('tool-result');
    box.hidden = false;
    box.textContent = '';
    box.className = `tool-result ${data.ok ? 'ok' : 'error'}`;

    const summary = document.createElement('div');
    summary.className = 'result-text';
    summary.textContent = data.result || '(sem resposta)';
    box.appendChild(summary);

    if (data.output_name) {
        const actions = document.createElement('div');
        actions.className = 'result-actions';

        const download = document.createElement('a');
        download.className = 'btn btn-small btn-primary';
        download.href = `/download/${encodeURIComponent(data.output_name)}`;
        download.textContent = 'Baixar';
        download.setAttribute('download', data.output_name);
        actions.appendChild(download);

        const isVideo = /\.(mp4|mkv|webm|mov)$/i.test(data.output_name);
        if (isVideo) {
            const use = document.createElement('button');
            use.type = 'button';
            use.className = 'btn btn-small btn-ghost';
            use.textContent = 'Usar como vídeo';
            use.addEventListener('click', () => {
                useVideoFile(
                    data.output_path,
                    `/preview/${encodeURIComponent(data.output_name)}`,
                    data.output_name,
                );
            });
            actions.appendChild(use);
        }

        box.appendChild(actions);
    }
}

// ---------------------------------------------------------------- Resultados

function setupButtons() {
    $('btn-refresh-results').addEventListener('click', () => refreshResults());
    $('btn-more-results').addEventListener('click', () => {
        resultsLimit += 12;
        renderResults();
    });
    $('btn-close-form').addEventListener('click', () => {
        $('tool-form-card').hidden = true;
        selectedTool = null;
        document.querySelectorAll('.tool-btn').forEach((btn) => btn.classList.remove('active'));
    });
    $('btn-new-chat').addEventListener('click', async () => {
        try {
            await fetch('/chat/reset', { method: 'POST' });
        } catch {
            /* sem servidor, limpa só a tela */
        }
        clearChat();
    });
}

function scheduleResultsRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => refreshResults({ scroll: true }), 300);
}

async function refreshResults({ scroll = false } = {}) {
    try {
        const response = await fetch('/outputs');
        if (!response.ok) return;
        allOutputs = await response.json();
        renderResults({ scroll });
    } catch {
        /* servidor indisponível; mantém a galeria atual */
    }
}

function renderResults({ scroll = false } = {}) {
    const grid = $('results-grid');
    grid.textContent = '';
    $('results-empty').hidden = allOutputs.length > 0;
    $('btn-more-results').hidden = allOutputs.length <= resultsLimit;

    const fresh = [];
    for (const item of allOutputs) {
        if (!knownOutputs.has(item.name)) {
            knownOutputs.add(item.name);
            if (!resultsFirstLoad) fresh.push(item.name);
        }
    }

    const visible = allOutputs.slice(0, resultsLimit);
    for (const item of visible) {
        grid.appendChild(buildResultCard(item, fresh.includes(item.name)));
    }

    resultsFirstLoad = false;

    if (scroll && fresh.length) {
        const first = grid.querySelector('.result-item.fresh') || grid.firstElementChild;
        if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

function buildResultCard(item, isFresh) {
    const card = document.createElement('article');
    card.className = `result-item${isFresh ? ' fresh' : ''}`;

    const media = document.createElement('div');
    media.className = 'result-media';

    if (item.kind === 'video') {
        const video = document.createElement('video');
        video.src = item.url;
        video.controls = true;
        video.preload = 'none';
        video.playsInline = true;
        media.appendChild(video);
    } else if (item.kind === 'image' || item.kind === 'gif') {
        const img = document.createElement('img');
        img.src = item.url;
        img.loading = 'lazy';
        img.alt = item.name;
        media.appendChild(img);
    } else if (item.kind === 'audio') {
        const icon = document.createElement('span');
        icon.className = 'media-icon';
        icon.textContent = '🎵';
        const audio = document.createElement('audio');
        audio.src = item.url;
        audio.controls = true;
        audio.preload = 'metadata';
        media.append(icon, audio);
    } else {
        const icon = document.createElement('span');
        icon.className = 'media-icon';
        icon.textContent = '📄';
        media.appendChild(icon);
    }

    const info = document.createElement('div');
    info.className = 'result-info';

    const name = document.createElement('span');
    name.className = 'result-name';
    name.textContent = item.name;
    name.title = item.path || item.name;

    const size = document.createElement('span');
    size.className = 'result-size';
    size.textContent = formatSize(item.size);

    info.append(name, size);

    const actions = document.createElement('div');
    actions.className = 'result-actions';

    const download = document.createElement('a');
    download.className = 'btn btn-small';
    download.href = item.download_url;
    download.textContent = 'Baixar';
    download.setAttribute('download', item.name);
    actions.appendChild(download);

    if (item.kind === 'video' && item.path) {
        const use = document.createElement('button');
        use.type = 'button';
        use.className = 'btn btn-small btn-ghost';
        use.textContent = 'Usar';
        use.addEventListener('click', () => useVideoFile(item.path, item.url, item.name));
        actions.appendChild(use);
    }

    card.append(media, info, actions);
    return card;
}

function formatSize(bytes) {
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
    if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
    if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${bytes} B`;
}

// ---------------------------------------------------------------- Chat

function setupChat() {
    $('btn-send').addEventListener('click', sendAICommand);
    $('ai-command').addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            sendAICommand();
        }
    });
    $('agent-status').addEventListener('click', checkAgentStatus);
}

async function sendAICommand() {
    const input = $('ai-command');
    const command = input.value.trim();
    if (!command) return;

    addChatMessage('user', command);
    input.value = '';
    input.disabled = true;
    $('btn-send').disabled = true;
    $('chat-state').textContent = 'trabalhando';
    showProgress('IA pensando...');

    const body = new FormData();
    body.append('message', command);
    if (currentVideoPath) body.append('file_path', currentVideoPath);
    myTurnId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    body.append('turn_id', myTurnId);

    try {
        const response = await fetch('/chat', { method: 'POST', body });
        const data = await response.json();
        addChatMessage(data.error ? 'assistant error' : 'assistant', data.answer || '(sem resposta)');
    } catch (error) {
        addChatMessage('assistant error', `Falha ao falar com a IA: ${error.message}`);
    } finally {
        myTurnId = null;
        input.disabled = false;
        $('btn-send').disabled = false;
        input.focus();
        $('chat-state').textContent = 'pronta';
        hideProgress();
    }
}

function addChatMessage(role, text) {
    const messages = $('chat-messages');
    const line = document.createElement('div');
    line.className = `chat-message ${role}`;
    line.textContent = text;
    messages.appendChild(line);
    while (messages.children.length > 200) messages.removeChild(messages.firstElementChild);
    messages.scrollTop = messages.scrollHeight;
}

function clearChat() {
    $('chat-messages').textContent = '';
    $('chat-state').textContent = 'pronta';
}

async function checkAgentStatus() {
    const badge = $('agent-status');
    badge.className = 'status checking';
    badge.textContent = 'Verificando IA...';

    try {
        const response = await fetch('/agent-status');
        const status = await response.json();
        if (status.connected && status.has_matching_model) {
            badge.textContent = `IA conectada · ${status.model}`;
            badge.className = 'status ok';
            badge.title = status.model;
        } else if (status.connected) {
            badge.textContent = 'IA conectada · modelo não encontrado';
            badge.className = 'status warn';
            badge.title = status.error || `Modelo: ${status.model}`;
        } else {
            badge.textContent = 'IA desconectada';
            badge.className = 'status fail';
            badge.title = status.error || 'LM Studio inacessível';
        }
    } catch {
        badge.textContent = 'Servidor sem resposta';
        badge.className = 'status fail';
        badge.title = '';
    }
}

// ---------------------------------------------------------------- Feedback

function showProgress(text) {
    $('progress-text').textContent = text;
    $('progress').hidden = false;
}

function hideProgress() {
    $('progress').hidden = true;
}

let toastTimer = null;
function toast(text) {
    const box = $('toast');
    box.textContent = text;
    box.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        box.hidden = true;
    }, 3500);
}
