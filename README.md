# ClipMind

**Editor de vídeo inteligente com IA local**

ClipMind usa LM Studio com tool calling real para executar FFmpeg de verdade. Você conversa em português, a IA escolhe a ferramenta, executa a edição e entrega o arquivo — sem copiar e colar comandos.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![FFmpeg](https://img.shields.io/badge/FFmpeg-required-green.svg)

---

## Índice

- [Sobre](#sobre)
- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
  - [Editor profissional](#editor-profissional)
- [Ferramentas](#ferramentas)
- [Configuração](#configuração)
- [Arquitetura](#arquitetura)
- [Testes](#testes)
- [Expansão](#expansão)
- [Troubleshooting](#troubleshooting)
- [Licença](#licença)

---

## Sobre

ClipMind transforma pedidos em edições reais. A IA conversa com você, decide qual ferramenta usar, o SDK executa a função Python correspondente e cada função roda FFmpeg via `subprocess`. O resultado volta para a IA e para a interface em tempo real.

A mesma camada de IA atende três superfícies:

- **Editor profissional** (`/editor`) — projeto com timeline de faixas, cortes não destrutivos, undo/redo, versões, prévia e export em segundo plano com controle de qualidade.
- **Web** (`server.py`, raiz) — paleta com as 23 ferramentas de arquivo único, formulários gerados a partir do catálogo, preview, chat em linguagem natural e galeria de resultados.
- **CLI** (`editor_agent.py`) — o mesmo agente em modo conversa no terminal.

---

## Recursos

**Editor profissional**
- Projeto salvo em JSON com faixas de vídeo, sobreposição, títulos, legendas e áudio
- Cortar, dividir, mover, duplicar, apagar, trim nas bordas e ripple/roll/slip/slide
- Snap, marcadores, regiões, zoom da régua e seleção por in/out
- Undo/redo na sessão, 30 versões por projeto no disco e autosave atômico
- Transição fade, velocidade 0,1x–8x, transformação (posição, escala, rotação, opacidade) e cor por clipe
- Títulos com `drawtext` e legendas queimadas com alinhamento determinístico (`.srt`/`.vtt`/`.ass`)
- Render em thread separada com progresso, cancelamento, log, QC por ffprobe e saída em arquivo novo
- Prévia leve (360p) separada da exportação final
- 21 skills de método carregadas sob demanda; a IA só chama as 19 ferramentas do motor, nunca um comando de shell

**Edição**
- Corte simples, cortes múltiplos em um só arquivo e junção de vídeos
- Remoção de silêncios com jump cuts (áudio e vídeo permanecem sincronizados)
- Aceleração/desaceleração, fade, rotação, recorte de área e repetição
- Texto sobre o vídeo e gravação de legendas `.srt`/`.ass`/`.vtt`
- Detecção de cenas

**Formato e entrega**
- Otimização para YouTube (H.264/AAC, faststart)
- Conversão para MP4, MKV, WebM e MOV
- Verticalização para Shorts/Reels (fundo desfocado ou corte central)
- Compressão com tamanho alvo em MB
- Thumbnail, folha de contatos e GIF

**Áudio**
- Extração em MP3, WAV ou M4A
- Normalização de volume para -14 LUFS
- Música de fundo com volume ajustável

**Experiência**
- Tool calling real com encadeamento de ferramentas
- Feedback em tempo real por WebSocket (ferramenta atual, resultado, progresso de carregamento do modelo)
- Resultados sempre em arquivos novos (numeração `_2`, `_3`, ...), sem sobrescrever edições anteriores
- Galeria com preview de vídeo, imagem e áudio, download e reutilização como entrada

---

## Requisitos

- **Python 3.10+**
- **FFmpeg** e **ffprobe** no PATH
- **LM Studio** com o servidor local iniciado
- **Modelo com suporte a tool calling** (família Qwen 2.5/3 funciona bem)

---

## Instalação

### 1. Instalar FFmpeg

**Windows:**

```powershell
winget install FFmpeg
```

Ou baixe em [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/), extraia e adicione a pasta `bin` ao PATH.

**Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

Confirme:

```bash
ffmpeg -version
ffprobe -version
```

### 2. Instalar LM Studio

1. Baixe em [https://lmstudio.ai/](https://lmstudio.ai/)
2. Na aba **Discover**, baixe um modelo com tool calling
3. Na aba **Developer**, inicie o servidor local
4. Deixe a autenticação desativada (veja [Autenticação](#autenticação-do-lm-studio-importante))

### 3. Instalar dependências Python

```bash
git clone https://github.com/DouglasGDev/clipmind.git
cd clipmind
pip install -r requirements.txt
```

### 4. Verificar instalação

```bash
ffmpeg -version
python -c "import lmstudio; print('SDK OK')"
lms ps     # modelos carregados
lms ls     # modelos baixados
python -c "import asyncio, agent; print(asyncio.run(agent.agent_status()))"
```

O último comando deve retornar `"connected": True`. Se vier `False` com aviso de API token, veja [Autenticação](#autenticação-do-lm-studio-importante).

---

## Uso

### Interface Web

```bash
python server.py
```

Acesse **http://localhost:8000**.

Fluxo típico:

1. Envie um vídeo (arrastar ou **Selecionar vídeo**). O arquivo é copiado para `uploads/` mantendo o nome original.
2. O cartão **Informações** mostra duração, resolução, FPS, codecs e tamanho.
3. Use a timeline e os botões **Marcar início** / **Marcar fim** para preencher o corte.
4. Escolha uma ferramenta na paleta, ajuste os campos e clique em **Executar** — ou peça em português no chat da IA.
5. O resultado aparece na galeria; use **Usar** para continuar editando a partir dele.

Os campos de caminho aceitam upload direto: **Escolher** para vídeo, **Enviar** para música ou legenda e **Adicionar** para juntar vários vídeos.

O selo no topo mostra o estado da IA e pode ser clicado para verificar de novo. **Nova conversa** limpa o histórico do agente.

### Editor profissional

```bash
python server.py
```

Acesse **http://localhost:8000/editor**. É um editor multipista de verdade: a timeline, o inspector e os botões funcionam sem IA, e a IA usa as mesmas operações da interface.

Fluxo típico:

1. **Novo projeto** — nome, largura, altura e fps. O projeto vira JSON em `./projects/<id>/`, versionado a cada mudança.
2. **Mídia** — arraste arquivos ou use **Enviar arquivo**. Duplo clique em um item coloca o clipe na faixa ativa.
3. **Timeline** — arraste um clipe para mover, puxe a borda para aparar, `S` divide no playhead. Faixas: `v1`/`v2` (vídeo), `t1` (títulos), `s1` (legendas), `a1` (áudio). Snap, marcadores, zoom e regiões de trabalho estão na barra da timeline.
4. **Clipe** (inspector) — volume, fades, velocidade (0,1x a 8x), escala/posição/opacidade e cor por clipe.
5. **Histórico** — `Ctrl+Z` / `Ctrl+Shift+Z` desfaz e refaz qualquer operação; a aba **Projeto → Versões** guarda os 30 últimos snapshots e restaura qualquer um.
6. **Prévia** — render 360p em thread separada, com progresso, log e cancelamento. A prévia não apaga a exportação: são arquivos novos.
7. **Exportar** — render na resolução do projeto, com presets de formato/qualidade.
8. **Controle de qualidade** — depois de cada render, `ffprobe` confirma resolução, fps, duração, loudness (EBU R128), true peak, faixas de preto e o delta áudio/vídeo.
9. **IA** — descreva o trabalho em português; o agente chama as ferramentas da timeline e a interface reflete cada mudança em tempo real. O painel **Skills** carrega o guia do gênero no contexto da conversa.

Atalhos: `Espaço` play/pause · `S` dividir · `M` marcador · `Delete` excluir · `←`/`→` um frame · `Shift+←`/`Shift+→` um segundo · `Ctrl+Z` desfazer · `Ctrl+Y` refazer.

#### Endpoints do editor

| Método | Rota | Função |
|--------|------|--------|
| `GET` | `/editor` | Interface do editor profissional |
| `GET` | `/api/editor/status` | Conexão, modelo e quantidade de skills |
| `GET` / `POST` | `/api/editor/projects` | Lista projetos ou cria um novo (`name`, `width`, `height`, `fps`) |
| `POST` | `/api/editor/projects/{id}/activate` | Marca o projeto ativo |
| `GET` / `DELETE` | `/api/editor/projects/{id}` | Estado completo (ou apagar, com `?confirm=true`) |
| `POST` | `/api/editor/projects/{id}/operations` | Aplica uma operação da timeline (`operation` + `params`) |
| `POST` | `/api/editor/projects/{id}/undo` · `/redo` | Desfaz / refaz a última operação |
| `GET` | `/api/editor/projects/{id}/versions` | Versões gravadas em disco |
| `POST` | `/api/editor/projects/{id}/versions/{versão}/restore` | Restaura uma versão |
| `GET` | `/api/editor/projects/{id}/validate` | Issues do projeto, com severidade |
| `POST` | `/api/editor/projects/{id}/render` | Enfileira prévia ou export (`preview`, `format`, `crf`, ...) |
| `GET` / `DELETE` | `/api/editor/jobs/{job_id}` | Status de uma renderização / cancela |
| `POST` | `/api/editor/jobs/{job_id}/validate` | QC do arquivo gerado |
| `GET` | `/api/editor/projects/{id}/jobs` · `/preview` | Filas do projeto / última prévia concluída |
| `GET` | `/api/editor/media?path=` | Serve mídia do projeto (contida em pasta conhecida) |
| `GET` | `/api/editor/uploads` | Arquivos enviados prontos para inserir |
| `GET` | `/api/editor/skills` · `/skills/{nome}` | Lista as 21 skills / carrega uma |
| `POST` | `/api/editor/projects/{id}/chat` | Turno da IA na timeline (`message`, `turn_id`) |
| `POST` | `/api/editor/projects/{id}/chat/reset` | Limpa a conversa daquele projeto |

As operações aceitas em `/operations` são: `add_clip`, `add_text`, `add_subtitles`, `move`, `trim`, `split`, `delete`, `duplicate`, `slip`, `slide`, `roll`, `set`, `add_track`, `remove_track`, `set_track`, `add_marker`, `remove_marker`, `add_region`, `settings`.

Erros seguem a regra de sempre: `400` para pedido malformado, `404` para projeto/clipe/versão inexistente, `409` quando a renderização ainda não terminou — sempre com a mensagem em `detail`, sem traceback.

### Interface Terminal

```bash
python editor_agent.py
```

Comandos: `ajuda`, `status`, `sair`.

### Endpoints da API

| Método | Rota | Função |
|--------|------|--------|
| `GET` | `/` | Interface web |
| `WS` | `/ws` | Eventos em tempo real |
| `GET` | `/agent-status` | Conexão e modelo do LM Studio |
| `GET` | `/tools` | Catálogo das 23 ferramentas (com campos) |
| `POST` | `/tool/{name}` | Executa uma ferramenta com JSON de campos |
| `POST` | `/upload` | Envia um arquivo e devolve o caminho local |
| `GET` | `/media-info?path=` | Metadados do vídeo (ffprobe) |
| `POST` | `/chat` | Turno do agente (`message`, `file_path`, `turn_id`) |
| `POST` | `/chat/reset` | Descarta o histórico do agente |
| `GET` | `/outputs` | Lista os arquivos gerados |
| `GET` | `/preview/{nome}` | Serve um arquivo gerado (com Range) |
| `GET` | `/download/{nome}` | Baixa um arquivo gerado |

Exemplo de chamada direta:

```bash
curl -X POST http://localhost:8000/tool/cut_video \
  -H "Content-Type: application/json" \
  -d '{"video_path":"C:/Videos/aula.mp4","start":"00:01:30","end":"00:05:00"}'
```

A resposta traz `ok`, `result`, `output_path` e `output_name`. Erros de validação retornam HTTP 4xx com `detail`.

### Exemplos de comandos para a IA

```
Analise o vídeo C:/Videos/aula.mp4 e me diga a duração
Corte o vídeo aula.mp4 de 00:01:30 até 00:05:00
Remova os silêncios de podcast.mp4 e depois normalize o volume
Junte intro.mp4 e aula.mp4 em um único vídeo
Deixe esse vídeo vertical para Shorts com fundo desfocado
Otimize final.mp4 para o YouTube em 1080p
Crie uma thumbnail do vlog.mp4 aos 15 segundos
Extraia o áudio de musica.mp4 em MP3
Corte os trechos 00:00:05-00:00:12 e 00:02:00-00:02:40 de aula.mp4
Escreva "Inscreva-se" no rodapé do vídeo
Grave a legenda legenda.srt no vídeo
```

---

## Ferramentas

Todas as funções são reais: executam FFmpeg e salvam em `./output/`.

| Ferramenta | O que faz | Técnica |
|------------|-----------|---------|
| `inspect_video` | Metadados completos do vídeo | `ffprobe -show_format -show_streams` |
| `detect_scenes` | Lista cortes de cena com tempo e score | filtro `scdet` (1–100) |
| `cut_video` | Extrai um trecho | `-c copy`; re-encode automático se o corte ficar sem imagem |
| `cut_multiple_segments` | Vários trechos em um só arquivo | `trim`/`atrim` + `concat` |
| `remove_silence` | Remove pausas | `silencedetect` + jump cuts `trim`/`atrim` + `concat` |
| `join_videos` | Junta vídeos na ordem | concat demuxer; normalização quando os formatos diferem |
| `optimize_for_youtube` | Padrão de upload do YouTube | `libx264` CRF 23 + AAC 192k + `faststart`, escala sem distorcer |
| `resize_for_shorts` | Vertical 1080x1920 | fundo desfocado (`blur`) ou corte central (`crop`) |
| `compress_video` | Reduz para um tamanho alvo | cálculo de bitrate + 2 passadas |
| `convert_video` | MP4, MKV, WebM ou MOV | H.264/AAC ou VP9/Opus no WebM |
| `create_thumbnail` | Capa JPG de um frame | `-vframes 1 -q:v 2` |
| `create_contact_sheet` | Grade de frames | `tile` (colunas × linhas) |
| `create_gif` | GIF animado de um trecho | `palettegen` + `paletteuse` |
| `extract_audio` | Áudio em MP3, WAV ou M4A | `libmp3lame` 192k / PCM / AAC |
| `normalize_audio` | Loudness de YouTube | `loudnorm I=-14 TP=-1.5:LRA=11` |
| `add_music` | Música de fundo | `amix` (mantém o original) ou substituição |
| `change_speed` | 0.25x a 4x | `setpts` + cadeia `atempo` |
| `fade_video` | Fade de entrada/saída | `fade` (vídeo e áudio) |
| `rotate_video` | Gira 90°, 180° ou 270° | `transpose`/`rotate` |
| `crop_video` | Recorta uma área | `crop=largura:altura:x:y` |
| `loop_video` | Repete o vídeo N vezes | `-stream_loop` |
| `add_text` | Texto sobre o vídeo | `drawtext` com fonte copiada e `textfile` |
| `burn_subtitles` | Grava legendas no vídeo | filtro `subtitles` com o `.srt` copiado |

Saídas são nomeadas a partir do arquivo original (`aula_cortado.mp4`, `aula_youtube.mp4`, `vlog_capa.jpg`). Se o nome já existir, o ClipMind cria `_2`, `_3`, ... — nenhuma edição anterior é sobrescrita.

Limites conhecidos:

- `cut_video` usa stream copy para ser rápido; se o trecho não tiver keyframe, a ferramenta detecta a saída sem imagem e refaz com re-encode.
- `remove_silence` limita a 300 cortes por vídeo para não gerar um filtro gigante; ajuste o limiar se o áudio tiver muito ruído.
- `add_text` usa fontes do Windows (Arial/Segoe UI). Em Linux, instale `fonts-dejavu-core` ou ajuste `_font_path`.
- `burn_subtitles` aceita `.srt`, `.ass` e `.vtt`.

---

## Configuração

### Autenticação do LM Studio (importante)

Por padrão o LM Studio **não** exige autenticação. Se você ativou o switch de autenticação em **Developer → Server Settings**, toda chamada (REST, SDK Python, SDK TypeScript) passa a exigir um API token.

No SDK Python 1.5.0 não há parâmetro para enviar token ao cliente local, então conecte-se a um servidor **sem autenticação exigida**:

- LM Studio → aba **Developer** → **Server Settings** → desative o switch de autenticação; e
- deixe **Network Interface** em `127.0.0.1`, a menos que precise expor na rede.

Atenção: trocar a Network Interface para `127.0.0.1` **não** dispensa o token. A API interna usada pelo SDK (porta 41343) já é local e mesmo assim recusa a conexão enquanto o switch de autenticação estiver ligado. O que libera o SDK é desativar a autenticação.

Sem isso o ClipMind mostra na tela exatamente qual é o bloqueio, em vez de falhar silencioso.

### Modelo usado

Por padrão o ClipMind **detecta o modelo**: usa o que estiver carregado no LM Studio; se nenhum estiver, usa o único LLM baixado. Para fixar um modelo:

**Windows (PowerShell):**

```powershell
$env:CLIPMIND_MODEL = "qwen/qwen3.8-27b"
python server.py
```

**Linux/macOS:**

```bash
export CLIPMIND_MODEL="qwen/qwen3.8-27b"
python server.py
```

| Variável | Padrão | Uso |
|----------|--------|-----|
| `CLIPMIND_MODEL` | auto | nome/chave do modelo no LM Studio |
| `CLIPMIND_LMS_HOST` | auto | `host:porta` da API local do LM Studio |
| `CLIPMIND_CONTEXT` | `16384` | contexto em tokens ao carregar o modelo |
| `CLIPMIND_PROJECTS` | `./projects` | pasta dos projetos do editor |
| `CLIPMIND_TURN_TIMEOUT` | `900` | segundos antes de cancelar um turno da IA na timeline |

As 23 ferramentas ocupam cerca de 5.700 tokens de contexto. Com 8k sobram
poucos tokens para o histórico: numa cadeia longa os primeiros resultados saem
da janela e o modelo pode inventar números no resumo final. Por isso o padrão é
16k. O LM Studio não recarrega um modelo já carregado só porque a configuração
mudou: se ele já estiver em memória com contexto menor, descarregue-o no LM
Studio (ou reinicie o servidor) para o ClipMind carregá-lo no tamanho novo.

Se a máquina não tiver memória para 16k, reduza:

```powershell
$env:CLIPMIND_CONTEXT = "8192"
```

### Pasta de saída

Os arquivos editados vão para `./output/`. Para mudar, edite `OUTPUT_DIR` no topo de `youtube_editor_tools.py`:

```python
OUTPUT_DIR = Path("./output")
# OUTPUT_DIR = Path("C:/MeusVideos/Editados")
```

### Porta do servidor

`server.py` usa a porta 8000 em `0.0.0.0`. Para expor apenas na máquina local ou trocar a porta:

```python
uvicorn.run(app, host="127.0.0.1", port=8000)
```

---

## Arquitetura

```
clipmind/
├── youtube_editor_tools.py   # 23 ferramentas FFmpeg + TOOL_SPECS (catálogo da interface)
├── agent.py                  # SDK LM Studio: .act() + tool calling (web e CLI)
├── server.py                 # FastAPI + WebSocket + endpoints das ferramentas
├── editor_agent.py           # Interface de terminal (reaproveita agent.py)
├── editor_project.py         # Motor do projeto: faixas, clipes, operações, undo/redo, versões
├── editor_render.py          # Render multipista em thread + progresso, cancelamento e QC
├── editor_api.py             # Rotas /api/editor/* e /editor (REST + eventos por WebSocket)
├── editor_skills.py          # Catálogo das 21 skills (SKILL.md em ./skills)
├── timeline_agent.py         # Agente da timeline: 19 ferramentas, histórico por projeto
├── templates/index.html      # Página da interface de ferramentas
├── templates/editor.html     # Página do editor profissional
├── static/style.css          # Estilos da interface de ferramentas
├── static/app.js             # Paleta, formulários, galeria, timeline e chat
├── static/editor.css         # Estilos do editor
├── static/editor.js          # Timeline, inspector, monitores, render e QC
├── skills/                   # 21 pastas com SKILL.md
├── docs/                     # ROADMAP_PROFESSIONAL_EDITOR.md e PROGRESSO.md
├── tests/                    # 641 testes (motor, API, render, skills, agente)
├── test_videos/              # Mídia de exemplo usada nos testes
├── requirements.txt          # Dependências Python
├── README.md
├── LICENSE
├── output/                   # Arquivos renderizados (gerada automaticamente)
├── projects/                 # Projetos do editor (gerada automaticamente)
└── uploads/                  # Arquivos enviados pela interface
```

### Como funciona

1. **Conexão** — `agent.py` abre `AsyncClient` na API local do LM Studio (porta interna 41343) e resolve o modelo (`llm.model()` carrega sob demanda, com progresso reportado à interface).
2. **Chat** — mantém um `lms.Chat(SYSTEM_PROMPT)` compartilhado entre pedidos; `/chat/reset` descarta o histórico.
3. **Turno** — a interface chama `run_agent_turn(texto, on_event)`.
4. **Tool calling** — `llm.act(chat, TOOLS, on_message=...)` roda o loop: o modelo pede a ferramenta, o SDK chama a função Python, o resultado volta ao modelo, e assim por diante.
5. **Eventos** — cada chamada e resultado é transmitido por WebSocket. `toolCallRequest`/`toolCallResult` do wire format do SDK são traduzidos em eventos simples; a aba que fez o pedido usa o `turn_id` para não duplicar mensagens.
6. **FFmpeg** — cada ferramenta monta a linha de comando com `subprocess.run`, valida a saída e retorna o caminho absoluto.
7. **Galeria** — `/outputs` lê `./output`, e `/preview`/`/download` só servem arquivos contidos nessa pasta (sem travessia de diretório).

O painel manual usa o mesmo registro de funções do agente: `/tool/{name}` aceita apenas nomes da whitelist e deriva os parâmetros da assinatura Python.

### O motor do editor

1. **Projeto é JSON** — `editor_project.py` guarda faixas, clipes, marcadores e regiões num arquivo por projeto. Nada é destrutivo: o clipe referencia o arquivo original com `in`/`out`, `start` e `speed`; o corte acontece na renderização.
2. **Operações nomeadas** — a API e a IA passam pelo mesmo `apply_operation`. Cada uma valida colisões, limites e cores antes de gravar e rejeita o que não conhece, então nenhum cliente escreve campo fora do contrato.
3. **Gravação atômica** — escrita em arquivo temporário + `os.replace`; cada mudança empilha um snapshot (undo/redo na sessão, 30 versões em disco). Operação sem efeito não consome passo nem versão.
4. **Render** — `editor_render.py` monta um filtro por clipe (`trim`/`scale`/`setsar`/`eq`/`fade`/`drawtext`/`ass`), empilha as faixas na ordem e roda `ffmpeg -progress pipe:1` numa thread: a interface continua respondendo, mostra porcentagem e pode cancelar.
5. **Conferência** — terminado o render, `validate_render` roda `ffprobe` e os filtros `blackdetect` e `ebur128` e devolve resolução, fps, duração, loudness, true peak, pretos e o delta entre áudio e vídeo. Se o arquivo não bate com o projeto, o QC diz — não a sorte.
6. **Prévia separada** — prévia é 360p/CRF 28 e export é a resolução do projeto; ambos geram arquivo novo, nunca sobrescrevem.
7. **IA sem poder arbitrário** — `timeline_agent.py` expõe 19 ferramentas que só chamam o motor. O modelo nunca monta linha de comando: pede `split`, `remove_silence` ou `set` e o validador do projeto decide se vale.

---

## Testes

```bash
python -m pytest tests -q
```

São **641 testes** em ~15 s e nenhum deles precisa do LM Studio: o agente é exercitado com um cliente LLM falso, que devolve `toolCallRequest` de verdade para confirmar o encadeamento, os eventos e as mensagens de erro.

| Arquivo | O que cobre |
|---------|-------------|
| `tests/test_project_engine.py` | Operações da timeline, colisões, ripple/roll/slip/slide, undo/redo, versões, validação |
| `tests/test_api.py` | Todas as rotas `/api/*` e `/tool/*`, códigos 400/404/409, corpo malformado, limites |
| `tests/test_render.py` | Linha de comando do FFmpeg, prévia vs. export, cancelamento, QC, arquivos novos |
| `tests/test_skills.py` | As 21 skills: seções obrigatórias, front matter e carregamento sob demanda |
| `tests/test_timeline_agent.py` | As 19 ferramentas da IA, rejeição de parâmetros, prompt de sistema e integração com o LM Studio |

As renderizações de verdade usam `test_videos/` e são conferidas com `ffprobe`, não só com comparação de texto. Sem a mídia no lugar, esses testes são pulados com aviso — o resto roda igual.

---

## Expansão

Para adicionar uma ferramenta:

1. Escreva a função em `youtube_editor_tools.py` com type hints e docstring (a docstring é o que o modelo lê).
2. Registre em `TOOL_SPECS` com nome, rótulo, ícone, grupo e campos do formulário.
3. Importe a função em `agent.py` e adicione em `TOOLS` (a IA passa a usá-la).
4. Importe em `server.py` e adicione à whitelist `FERRAMENTAS` (o painel passa a executá-la).

Exemplo mínimo:

```python
def extract_frame(video_path: str, time: str = "00:00:05") -> str:
    """
    Salva um frame do vídeo como imagem PNG.

    Args:
        video_path: caminho do vídeo.
        time: momento do frame no formato HH:MM:SS.

    Returns:
        Caminho do arquivo gerado ou mensagem de erro.
    """
    erro = _check_file(video_path)
    if erro:
        return erro
    saida = get_output_path(video_path, "_frame", ".png")
    ok, msg = run_ffmpeg(["-y", "-i", video_path, "-ss", time, "-vframes", "1", str(saida)])
    return f"Frame salvo em: {saida.absolute()}" if ok else msg
```

```python
# youtube_editor_tools.py
TOOL_SPECS.append({
    "name": "extract_frame", "label": "Extrair frame", "icon": "🖼️", "group": "Entrega",
    "fields": [
        {"name": "video_path", "type": "video", "label": "Vídeo"},
        {"name": "time", "label": "Momento", "default": "00:00:05"},
    ],
})
```

Adicione `extract_frame` em `TOOLS` (`agent.py`) e em `FERRAMENTAS` (`server.py`). A interface monta o formulário sozinha a partir de `TOOL_SPECS`.

---

## Troubleshooting

### "FFmpeg não encontrado"

Instale e adicione ao PATH:

```bash
ffmpeg -version
winget install FFmpeg   # Windows
```

### "LM Studio não acessível"

1. Abra o LM Studio
2. Inicie o servidor na aba **Developer**
3. Confira `lms ps` e `lms ls`
4. Clique no selo de status da interface para verificar de novo

### "The LM Studio API token provided was not recognized"

O switch de autenticação está ligado em **Developer → Server Settings**. Desative-o e reinicie o servidor. O SDK Python 1.5.0 não consegue enviar token ao cliente local.

> Um bug do SDK 1.5.0 faz essa falha chegar como
> `ValueError: dictionary update sequence element #0...` em vez do erro de
> autenticação. O ClipMind reconhece esse texto e mostra o aviso correto.

### "O modelo não chama as ferramentas"

1. Use um modelo com bom suporte a tool calling (Qwen 2.5/3, por exemplo)
2. Seja específico: "corte aula.mp4 de 00:01:00 até 00:03:00"
3. Confira o selo de status ou `GET /agent-status`
4. Se o modelo estiver carregando, a interface mostra o progresso; um modelo grande pode levar minutos na primeira vez

### "Arquivo não encontrado"

Use caminho completo (`C:/Videos/meu_video.mp4`) ou envie o arquivo pela interface. Dentro do app, os caminhos são preenchidos automaticamente.

### Corte saiu sem imagem ou com duração errada

O ClipMind valida o arquivo gerado. Se o stream copy falhar por falta de keyframe, refaz o corte com re-encode automaticamente. Se o problema persistir, verifique o vídeo com `ffprobe` e teste o corte com outro trecho.

### Texto ou legenda não aparecem

`add_text` usa fontes do Windows e `burn_subtitles` usa o filtro `subtitles`. Em Linux, instale `fonts-dejavu-core`. Verifique também se o `.srt` está em UTF-8 e com tempos válidos.

### Porta 8000 ocupada

Encerre o processo que está na porta ou troque a porta em `server.py`:

```bash
netstat -ano | findstr :8000
```

---

## Licença

MIT — veja [LICENSE](LICENSE).

Copyright (c) 2026 Douglas da Silva Groff

---

## Contribuindo

Contribuições são bem-vindas: reporte bugs, sugira ferramentas e envie pull requests.

## Autor

**Douglas da Silva Groff** — [GitHub](https://github.com/DouglasGDev)

## Agradecimentos

- [LM Studio](https://lmstudio.ai/) — IA local com tool calling
- [FFmpeg](https://ffmpeg.org/) — processamento de vídeo
- Comunidade open-source
