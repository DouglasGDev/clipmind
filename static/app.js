// ClipMind - Interface JavaScript
let currentVideoPath = null;
let videoPlayer = null;
let ws = null;

// Inicialização
document.addEventListener('DOMContentLoaded', () => {
    setupDragDrop();
    setupVideoInput();
    setupWebSocket();
    videoPlayer = document.getElementById('video-player');
    setupTimeline();
    checkAgentStatus();
});

// WebSocket para feedback em tempo real
function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };
    
    ws.onclose = () => {
        console.log('WebSocket fechado, reconectando...');
        setTimeout(setupWebSocket, 3000);
    };
}

function handleWebSocketMessage(data) {
    if (data.type === 'processing') {
        showProgress(data.action);
    } else if (data.type === 'complete') {
        hideProgress();
    } else if (data.type === 'agent') {
        handleAgentEvent(data);
    }
}

// Eventos vindos do loop de tool calling da IA
function handleAgentEvent(event) {
    switch (event.kind) {
        case 'tool_call': {
            const args = event.args && Object.keys(event.args).length
                ? ` ${JSON.stringify(event.args)}`
                : '';
            addChatMessage('tool', `Chamando ${event.name}...${args}`);
            showProgress(`${event.name} em execução`);
            break;
        }
        case 'tool_result': {
            const res = (event.result || '').slice(0, 220);
            addChatMessage('tool', `${event.name || 'ferramenta'} → ${res}`);
            hideProgress();
            break;
        }
        case 'loading':
            showProgress(`Carregando modelo no LM Studio... ${event.progress}%`);
            break;
        case 'error':
            hideProgress();
            addChatMessage('assistant', event.text);
            break;
        case 'answer':
            hideProgress();
            break;
    }
}

// Drag and Drop
function setupDragDrop() {
    const uploadArea = document.getElementById('upload-area');
    
    uploadArea.addEventListener('dragover', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#764ba2';
        uploadArea.style.background = '#f8f9ff';
    });
    
    uploadArea.addEventListener('dragleave', () => {
        uploadArea.style.borderColor = '#667eea';
        uploadArea.style.background = 'white';
    });
    
    uploadArea.addEventListener('drop', (e) => {
        e.preventDefault();
        uploadArea.style.borderColor = '#667eea';
        uploadArea.style.background = 'white';
        
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('video/')) {
            handleVideoFile(file);
        }
    });
}

// Input de vídeo
function setupVideoInput() {
    const input = document.getElementById('video-input');
    input.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (file) {
            handleVideoFile(file);
        }
    });
}

async function handleVideoFile(file) {
    showProgress('Enviando vídeo...');
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/upload', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        currentVideoPath = data.file_path;
        
        // Mostra preview do vídeo
        const videoURL = URL.createObjectURL(file);
        videoPlayer.src = videoURL;
        
        document.getElementById('upload-area').style.display = 'none';
        document.getElementById('video-preview').style.display = 'block';
        document.getElementById('timeline').style.display = 'block';
        
        // Habilita botões
        enableToolButtons();
        
        hideProgress();
        addChatMessage('assistant', `Vídeo carregado: ${file.name}`);
        
    } catch (error) {
        hideProgress();
        addChatMessage('assistant', `Erro ao enviar vídeo: ${error.message}`);
    }
}

// Timeline
function setupTimeline() {
    const timelineBar = document.querySelector('.timeline-bar');
    
    timelineBar.addEventListener('click', (e) => {
        if (!videoPlayer || !videoPlayer.duration) return;
        
        const rect = timelineBar.getBoundingClientRect();
        const percent = (e.clientX - rect.left) / rect.width;
        const time = percent * videoPlayer.duration;
        
        videoPlayer.currentTime = time;
        updateTimelineProgress();
    });
    
    videoPlayer.addEventListener('timeupdate', updateTimelineProgress);
}

function updateTimelineProgress() {
    if (!videoPlayer || !videoPlayer.duration) return;
    
    const percent = (videoPlayer.currentTime / videoPlayer.duration) * 100;
    document.getElementById('timeline-progress').style.width = `${percent}%`;
}

function setCutPoint(type) {
    if (!videoPlayer) return;
    
    const time = formatTime(videoPlayer.currentTime);
    
    if (type === 'start') {
        document.getElementById('cut-start').value = time;
    } else {
        document.getElementById('cut-end').value = time;
    }
}

function formatTime(seconds) {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

// Ferramentas
function enableToolButtons() {
    document.querySelectorAll('.tool-btn').forEach(btn => {
        btn.disabled = false;
    });
}

async function analyzeVideo() {
    if (!currentVideoPath) return;
    
    showProgress('Analisando vídeo...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        
        const response = await fetch('/analyze', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        displayResults(data.result);
        addChatMessage('assistant', 'Análise do vídeo concluída!');
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

async function cutVideo() {
    if (!currentVideoPath) return;
    
    const start = document.getElementById('cut-start').value;
    const end = document.getElementById('cut-end').value;
    
    if (!start || !end) {
        addChatMessage('assistant', 'Por favor, defina o início e o fim do corte na timeline.');
        return;
    }
    
    showProgress('Cortando vídeo...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        formData.append('start', start);
        formData.append('end', end);
        
        const response = await fetch('/cut', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        addChatMessage('assistant', data.result);
        
        if (data.output_path) {
            showDownloadLink(data.output_path);
        }
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

async function createThumbnail() {
    if (!currentVideoPath) return;
    
    const time = document.getElementById('cut-start').value || '00:00:05';
    
    showProgress('Criando thumbnail...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        formData.append('time', time);
        
        const response = await fetch('/thumbnail', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        addChatMessage('assistant', data.result);
        
        if (data.output_path) {
            showDownloadLink(data.output_path);
        }
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

async function optimizeVideo() {
    if (!currentVideoPath) return;
    
    showProgress('Otimizando para YouTube...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        
        const response = await fetch('/optimize', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        addChatMessage('assistant', data.result);
        
        if (data.output_path) {
            showDownloadLink(data.output_path);
        }
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

async function removeSilence() {
    if (!currentVideoPath) return;
    
    showProgress('Removendo silêncio...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        
        const response = await fetch('/remove-silence', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        addChatMessage('assistant', data.result);
        
        if (data.output_path) {
            showDownloadLink(data.output_path);
        }
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

async function extractAudio() {
    if (!currentVideoPath) return;
    
    showProgress('Extraindo áudio...');
    
    try {
        const formData = new FormData();
        formData.append('file_path', currentVideoPath);
        
        const response = await fetch('/extract-audio', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        addChatMessage('assistant', data.result);
        
        if (data.output_path) {
            showDownloadLink(data.output_path);
        }
        
    } catch (error) {
        addChatMessage('assistant', `Erro: ${error.message}`);
    } finally {
        hideProgress();
    }
}

// Chat IA
async function sendAICommand() {
    const input = document.getElementById('ai-command');
    const command = input.value.trim();

    if (!command) return;

    addChatMessage('user', command);
    input.value = '';
    input.disabled = true;
    showProgress('IA pensando...');

    try {
        const formData = new FormData();
        formData.append('message', command);

        const response = await fetch('/chat', { method: 'POST', body: formData });
        const data = await response.json();

        hideProgress();
        addChatMessage('assistant', data.answer || '(sem resposta)');

        // Um pedido pode ter gerado arquivos novos
        if (data.answer && data.answer.includes('salvo em:')) refreshResults();
    } catch (error) {
        hideProgress();
        addChatMessage('assistant', `Erro ao falar com a IA: ${error.message}`);
    } finally {
        input.disabled = false;
        input.focus();
    }
}

function refreshResults() {
    document.getElementById('results').style.display = 'block';
}

// Status da IA no carregamento
async function checkAgentStatus() {
    try {
        const res = await fetch('/agent-status');
        const status = await res.json();
        const badge = document.getElementById('agent-status');
        if (!badge) return;

        if (status.connected && status.has_matching_model) {
            badge.textContent = `IA conectada · ${status.model}`;
            badge.className = 'status ok';
        } else if (status.connected) {
            badge.textContent = `LM Studio ok, mas modelo "${status.model}" não encontrado`;
            badge.className = 'status warn';
        } else {
            badge.textContent = 'IA desconectada — abra o LM Studio e inicie o servidor';
            badge.className = 'status fail';
        }
    } catch {
        /* servidor fora do ar; nada a fazer */
    }
}

function addChatMessage(role, text) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${role}`;
    messageDiv.textContent = text;
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Resultados
function displayResults(data) {
    const resultsDiv = document.getElementById('results');
    const contentDiv = document.getElementById('results-content');
    
    resultsDiv.style.display = 'block';
    
    if (typeof data === 'object') {
        contentDiv.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
        
        // Mostra info do vídeo
        if (data.duracao_formato) {
            document.getElementById('video-info').innerHTML = `
                <strong>Duração:</strong> ${data.duracao_formato} |
                <strong>Resolução:</strong> ${data.streams?.[0]?.resolucao || 'N/A'} |
                <strong>Codec:</strong> ${data.streams?.[0]?.codec || 'N/A'}
            `;
        }
    } else {
        contentDiv.innerHTML = `<div class="result-item">${data}</div>`;
    }
}

function showDownloadLink(outputPath) {
    if (!outputPath) return;
    
    const filename = outputPath.split('\\').pop().split('/').pop();
    const resultsDiv = document.getElementById('results');
    const contentDiv = document.getElementById('results-content');
    
    resultsDiv.style.display = 'block';
    contentDiv.innerHTML += `
        <div class="result-item success">
            <strong>Arquivo gerado:</strong> ${filename}<br>
            <a href="/download/${filename}" class="btn btn-small" download>Baixar</a>
        </div>
    `;
}

// Progress
function showProgress(text) {
    document.getElementById('progress-text').textContent = text;
    document.getElementById('progress').style.display = 'flex';
}

function hideProgress() {
    document.getElementById('progress').style.display = 'none';
}
