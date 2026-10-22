# ClipMind

**Editor de vídeo inteligente para YouTube com IA local**

ClipMind usa LM Studio com tool calling real para executar comandos FFmpeg automaticamente. Você conversa em português e a IA edita seus vídeos de verdade.

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
- [Exemplos](#exemplos)
- [Configuração](#configuração)
- [Arquitetura](#arquitetura)
- [Expansão](#expansão)
- [Troubleshooting](#troubleshooting)
- [Licença](#licença)

---

## Sobre

ClipMind transforma comandos de texto em edições reais de vídeo. Diferente de ferramentas que apenas geram comandos para você copiar e colar, o ClipMind **executa as operações diretamente** usando ferramentas reais via LM Studio.

A IA entende seu pedido em português, escolhe a ferramenta apropriada, executa o FFmpeg com os parâmetros corretos e retorna o resultado — tudo automaticamente.

---

## Recursos

- **Análise de vídeo** — duração, resolução, codec, FPS, bitrate
- **Corte preciso** — por tempo inicial/final ou duração
- **Thumbnails** — extração de frames em alta qualidade
- **Otimização YouTube** — H.264 + AAC + faststart (padrão YouTube)
- **Remoção de silêncio** — detecta e remove pausas longas automaticamente
- **Extração de áudio** — converte para MP3 192kbps
- **Interface em português** — converse naturalmente com a IA
- **Tool calling real** — a IA executa ferramentas de verdade, não gera texto

---

## Requisitos

- **Python 3.10+**
- **FFmpeg** instalado e disponível no PATH
- **LM Studio** rodando localmente com um modelo carregado
- **Modelo com suporte a tool calling** (recomendado: Qwen 2.5)

---

## Instalação

### 1. Instalar FFmpeg

FFmpeg é o motor de processamento de vídeo usado pelo ClipMind.

**Windows:**

Opção 1 — Winget (recomendado):
```powershell
winget install FFmpeg
```

Opção 2 — Download manual:
1. Baixe em [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/)
2. Extraia o arquivo ZIP (ex: `C:\ffmpeg`)
3. Adicione ao PATH do sistema:

```powershell
# PowerShell como Administrador
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\ffmpeg\bin", "User")
```

4. Reinicie o terminal e verifique:

```bash
ffmpeg -version
ffprobe -version
```

**Linux (Ubuntu/Debian):**

```bash
sudo apt update
sudo apt install ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

### 2. Instalar LM Studio

LM Studio é a interface local para rodar modelos de IA.

1. Baixe em [https://lmstudio.ai/](https://lmstudio.ai/)
2. Instale e abra o LM Studio
3. Na aba "Discover", busque e baixe um modelo:
   - **Recomendado:** `qwen2.5-14b-instruct` (melhor tool calling)
   - **Alternativa leve:** `qwen2.5-7b-instruct` (funciona em máquinas com menos RAM)
4. Vá para a aba "Local Server" e clique em **Start Server**
5. O servidor roda em `http://localhost:1234` por padrão

### 3. Instalar dependências Python

Clone o repositório e instale as dependências:

```bash
git clone https://github.com/DouglasGDev/clipmind.git
cd clipmind
pip install -r requirements.txt
```

O `requirements.txt` instala o SDK oficial do LM Studio:
```
lmstudio>=0.3.0
```

### 4. Verificar instalação

Teste se tudo está configurado corretamente:

```bash
# Verifica FFmpeg
ffmpeg -version

# Verifica SDK do LM Studio
python -c "import lmstudio; print('LM Studio SDK OK')"

# Lista modelos disponíveis no LM Studio
lms lm list
```

Se todos os comandos acima funcionarem, você está pronto para usar o ClipMind!

---

## Uso

### Iniciar o programa

```bash
python editor_agent.py
```

O programa carrega o modelo configurado e inicia um loop de conversa interativo.

### Interface

```
============================================================
  CLIPMIND - Editor de Vídeo Inteligente
  Powered by LM Studio + FFmpeg
============================================================

Carregando modelo: qwen2.5-14b-instruct
Aguarde, isso pode levar alguns segundos...

Modelo 'qwen2.5-14b-instruct' carregado com sucesso!

Estou pronto! Digite sua pergunta ou comando de edição.
Digite "ajuda" para ver exemplos, "sair" para encerrar.

Você: 
```

### Comandos disponíveis

| Comando | Ação |
|---------|------|
| `ajuda` | Mostra exemplos de uso |
| `sair` | Encerra o programa |
| `exit` | Encerra o programa |
| `quit` | Encerra o programa |

---

## Exemplos

### Análise de vídeo

```
Você: Analise o vídeo C:/Videos/meu_video.mp4

Processando...
  [Ferramenta] Chamando: inspect_video
  [Resultado] inspect_video: {"arquivo": "meu_video.mp4", "duracao_segundos": 300.5, ...}

IA: O vídeo foi analisado com sucesso! Aqui estão as informações:
- Duração: 5 minutos e 0.5 segundos
- Resolução: 1920x1080 (Full HD)
- Codec de vídeo: H.264
- Codec de áudio: AAC
- FPS: 30
- Bitrate total: 2.5 Mbps
```

### Cortar vídeo

```
Você: Corte o vídeo aula.mp4 do 00:01:30 até 00:05:00

Processando...
  [Ferramenta] Chamando: cut_video
  [Resultado] cut_video: Vídeo cortado com sucesso! Arquivo salvo em: E:\clipmind\output\aula_cortado.mp4

IA: Vídeo cortado com sucesso! O segmento de 00:01:30 até 00:05:00 foi extraído.
Arquivo salvo em: output/aula_cortado.mp4
```

### Criar thumbnail

```
Você: Crie uma thumbnail do vídeo vlog.mp4 aos 15 segundos

Processando...
  [Ferramenta] Chamando: create_thumbnail
  [Resultado] create_thumbnail: Thumbnail criada com sucesso! Imagem salva em: E:\clipmind\output\vlog_capa.jpg

IA: Thumbnail criada! Frame capturado aos 15 segundos.
Imagem salva em: output/vlog_capa.jpg (1920x1080, alta qualidade)
```

### Otimizar para YouTube

```
Você: Otimize o vídeo final.mp4 para o YouTube em 1080p

Processando...
  [Ferramenta] Chamando: optimize_for_youtube
  [Resultado] optimize_for_youtube: Vídeo otimizado para YouTube com sucesso!

IA: Vídeo otimizado para YouTube!
- Codec: H.264 (libx264)
- Resolução: 1920x1080
- Áudio: AAC 192kbps
- Faststart: ativado (playback antes do download completo)
Arquivo salvo em: output/final_youtube.mp4
```

### Remover silêncio

```
Você: Remova os silêncios do vídeo podcast.mp4

Processando...
  [Ferramenta] Chamando: remove_silence
  [Resultado] remove_silence: Silêncios removidos com sucesso!

IA: Silêncios removidos! Pausas maiores que 0.5 segundos foram cortadas.
Arquivo salvo em: output/podcast_sem_silencio.mp4
```

### Extrair áudio

```
Você: Extraia o áudio do vídeo musica.mp4

Processando...
  [Ferramenta] Chamando: extract_audio
  [Resultado] extract_audio: Áudio extraído com sucesso!

IA: Áudio extraído em formato MP3!
- Codec: MP3 (libmp3lame)
- Bitrate: 192kbps
- Sample rate: 44100 Hz
Arquivo salvo em: output/musica_audio.mp3
```

---

## Configuração

### Trocar o modelo

Edite a variável `MODEL_NAME` no topo do arquivo `editor_agent.py`:

```python
# Linha 23
MODEL_NAME = "qwen2.5-14b-instruct"  # Modelo recomendado
# MODEL_NAME = "qwen2.5-7b-instruct"  # Alternativa mais leve
# MODEL_NAME = "seu-modelo-aqui"      # Qualquer modelo carregado no LM Studio
```

### Trocar a pasta de saída

Por padrão, os arquivos editados são salvos em `./output/`. Para mudar:

Edite a variável `OUTPUT_DIR` no topo do arquivo `youtube_editor_tools.py`:

```python
# Linha 13
OUTPUT_DIR = Path("./output")
# OUTPUT_DIR = Path("C:/MeusVideos/Editados")  # Caminho personalizado
```

### Ajustar parâmetros de qualidade

**Thumbnail (create_thumbnail):**
- Qualidade JPG: parâmetro `-q:v` (2-31, menor = melhor)
- Tempo padrão: `00:00:05` (5 segundos)

**Otimização YouTube (optimize_for_youtube):**
- CRF: parâmetro `-crf` (18-28, menor = melhor qualidade, maior = menor arquivo)
- Preset: `-preset` (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)
- Bitrate áudio: `-b:a` (128k, 192k, 256k, 320k)

**Remoção de silêncio (remove_silence):**
- Limiar de ruído: `-30dB` (mais negativo = mais rigoroso)
- Duração mínima: `0.5` segundos

**Extração de áudio (extract_audio):**
- Bitrate MP3: `192k` (128k, 192k, 256k, 320k)
- Sample rate: `44100` Hz

---

## Arquitetura

```
clipmind/
├── youtube_editor_tools.py   # Ferramentas FFmpeg (6 funções)
├── editor_agent.py           # Agente LM Studio (loop de conversa)
├── requirements.txt          # Dependências Python
├── README.md                 # Este arquivo
├── LICENSE                   # Licença MIT
├── .gitignore                # Ignora output/, __pycache__/, etc.
└── output/                   # Pasta gerada automaticamente
    ├── video_cortado.mp4
    ├── video_youtube.mp4
    ├── video_capa.jpg
    ├── video_audio.mp3
    └── ...
```

### Como funciona

1. **Carregamento** — `editor_agent.py` carrega o modelo via `lms.llm(MODEL_NAME)`
2. **Chat** — Cria objeto `lms.Chat(SYSTEM_PROMPT)` para manter histórico
3. **Loop** — Usuário digita comando em português
4. **Tool calling** — `model.act(chat, tools, on_message=...)` executa o loop automático:
   - LLM analisa o pedido
   - LLM escolhe a ferramenta apropriada
   - SDK executa a função Python
   - Resultado é enviado de volta ao LLM
   - LLM gera resposta final
5. **FFmpeg** — Cada ferramenta chama `subprocess.run(["ffmpeg", ...])`
6. **Output** — Arquivos editados salvos em `./output/` com sufixos (`_cortado`, `_youtube`, etc.)

### Ferramentas implementadas

| Função | Descrição | FFmpeg |
|--------|-----------|--------|
| `inspect_video` | Analisa metadados do vídeo | `ffprobe -show_format -show_streams` |
| `cut_video` | Corta segmento do vídeo | `-ss START -to END -c copy` |
| `create_thumbnail` | Extrai frame como JPG | `-ss TIME -vframes 1 -q:v 2` |
| `optimize_for_youtube` | Otimiza para upload YouTube | `-c:v libx264 -crf 23 -c:a aac -movflags +faststart` |
| `remove_silence` | Remove pausas longas | `-af silenceremove=...` |
| `extract_audio` | Extrai áudio como MP3 | `-vn -acodec libmp3lame -ab 192k` |

---

## Expansão

Adicionar novas ferramentas é simples. Siga estes passos:

### 1. Criar a função em `youtube_editor_tools.py`

```python
def adicionar_marca_dagua(video_path: str, imagem_path: str, posicao: str = "bottomright") -> str:
    """
    Adiciona uma marca d'água (imagem) sobre o vídeo.
    
    A marca d'água é posicionada em um dos cantos do vídeo.
    Recomendado usar imagem PNG com transparência.
    
    Args:
        video_path: Caminho completo para o vídeo original
        imagem_path: Caminho completo para a imagem da marca d'água (PNG)
        posicao: Posição da marca (topleft, topright, bottomleft, bottomright)
    
    Returns:
        str: Mensagem de sucesso com caminho do arquivo, ou mensagem de erro
    """
    path = Path(video_path)
    
    if not path.exists():
        return f"Erro: Arquivo não encontrado: {video_path}"
    
    output_path = get_output_path(video_path, "_marca_dagua")
    
    # Mapeia posição para overlay do FFmpeg
    overlay_positions = {
        "topleft": "10:10",
        "topright": f"main_w-overlay_w-10:10",
        "bottomleft": f"10:main_h-overlay_h-10",
        "bottomright": f"main_w-overlay_w-10:main_h-overlay_h-10"
    }
    
    position = overlay_positions.get(posicao, overlay_positions["bottomright"])
    
    args = [
        "-y",
        "-i", str(path),
        "-i", imagem_path,
        "-filter_complex", f"overlay={position}",
        "-c:a", "copy",
        str(output_path)
    ]
    
    success, message = run_ffmpeg(args, "Erro ao adicionar marca d'água")
    
    if success:
        return f"Marca d'água adicionada! Arquivo salvo em: {output_path.absolute()}"
    else:
        return message
```

### 2. Importar em `editor_agent.py`

```python
from youtube_editor_tools import (
    inspect_video,
    cut_video,
    create_thumbnail,
    optimize_for_youtube,
    remove_silence,
    extract_audio,
    adicionar_marca_dagua,  # <-- Nova ferramenta
)
```

### 3. Adicionar à lista de ferramentas

```python
tools = [
    inspect_video,
    cut_video,
    create_thumbnail,
    optimize_for_youtube,
    remove_silence,
    extract_audio,
    adicionar_marca_dagua,  # <-- Nova ferramenta
]
```

### 4. Atualizar o system prompt (opcional)

Adicione descrição da nova ferramenta no `SYSTEM_PROMPT` em `editor_agent.py`:

```python
SYSTEM_PROMPT = """...
- adicionar_marca_dagua: Adiciona marca d'água sobre o vídeo
...
"""
```

**Dica:** A docstring da função é o que a IA usa para entender quando e como usar a ferramenta. Seja claro e detalhado!

---

## Troubleshooting

### "FFmpeg não encontrado"

**Causa:** FFmpeg não está instalado ou não está no PATH.

**Solução:**
```bash
# Verifica se FFmpeg está instalado
ffmpeg -version

# Se não estiver, instale (Windows)
winget install FFmpeg

# Ou baixe em https://www.gyan.dev/ffmpeg/builds/
```

### "Erro ao carregar modelo"

**Causa:** LM Studio não está rodando ou modelo não está carregado.

**Solução:**
1. Abra o LM Studio
2. Vá para "Local Server" e clique em **Start Server**
3. Verifique se o modelo está carregado na aba "My Models"
4. Teste no terminal:

```bash
lms lm list
```

### "O modelo não chama as ferramentas"

**Causa:** Modelo não tem bom suporte a tool calling ou comando não está claro.

**Solução:**
1. Use modelos recomendados: `qwen2.5-14b-instruct` ou `qwen2.5-7b-instruct`
2. Seja específico nos comandos:
   - Ruim: "edita esse vídeo"
   - Bom: "Corte o vídeo aula.mp4 do 00:01:00 até 00:03:00"
3. Verifique se o servidor LM Studio está rodando em `http://localhost:1234`

### "Arquivo não encontrado"

**Causa:** Caminho do vídeo está incorreto.

**Solução:**
1. Use caminho completo: `C:/Videos/meu_video.mp4` (Windows) ou `/home/user/video.mp4` (Linux/Mac)
2. Verifique se o arquivo existe
3. Use barras normais (`/`) ou duplas (`\\`) no Windows

### "Erro ao executar FFmpeg"

**Causa:** Parâmetros inválidos ou arquivo de entrada corrompido.

**Solução:**
1. Verifique se o vídeo de entrada é válido: `ffprobe video.mp4`
2. Teste o comando FFmpeg manualmente para ver o erro completo
3. Verifique se há espaço em disco suficiente

---

## Licença

Este projeto está licenciado sob a **MIT License** — veja o arquivo [LICENSE](LICENSE) para detalhes.

```
MIT License

Copyright (c) 2026 Douglas Gonçalves

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software...
```

---

## Contribuindo

Contribuições são bem-vindas! Sinta-se à vontade para:

- Reportar bugs
- Sugerir novas funcionalidades
- Enviar pull requests
- Melhorar a documentação

---

## Autor

**Douglas da Silva Groff** — [GitHub](https://github.com/DouglasGDev)

---

## Agradecimentos

- [LM Studio](https://lmstudio.ai/) — Plataforma local para IA
- [FFmpeg](https://ffmpeg.org/) — Motor de processamento de vídeo
- Comunidade open-source

---

**Divirta-se editando vídeos com IA!**
