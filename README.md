# ClipMind

Editor de vídeo inteligente para YouTube usando **LM Studio local** com **tool calling real**. Você conversa em português e a IA edita o vídeo de verdade com FFmpeg.

---

## Sobre

ClipMind transforma comandos de voz/texto em edições reais de vídeo. Diferente de ferramentas que apenas geram comandos para você copiar e colar, o ClipMind executa as operações diretamente usando ferramentas reais via LM Studio.

## Requisitos

- **Python 3.10+**
- **FFmpeg** instalado e disponível no PATH
- **LM Studio** rodando localmente com um modelo carregado

---

## Instalação

### 1. Instalar FFmpeg

**Windows:**

Baixe o FFmpeg em [https://www.gyan.dev/ffmpeg/builds/](https://www.gyan.dev/ffmpeg/builds/) (versão `ffmpeg-release-essentials.zip`).

Extraia e adicione ao PATH:

```powershell
# Adicione ao PATH do sistema (PowerShell como Admin)
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\ffmpeg\bin", "User")
```

Ou use o winget:

```powershell
winget install FFmpeg
```

**Linux:**

```bash
sudo apt install ffmpeg
```

**macOS:**

```bash
brew install ffmpeg
```

Verifique a instalação:

```bash
ffmpeg -version
ffprobe -version
```

### 2. Instalar LM Studio

Baixe em [https://lmstudio.ai/](https://lmstudio.ai/) e instale.

Dentro do LM Studio, baixe um modelo com bom suporte a tool calling:

- **Recomendado:** `qwen2.5-14b-instruct`
- **Alternativa leve:** `qwen2.5-7b-instruct`

Inicie o servidor local do LM Studio (padrão: `http://localhost:1234`).

### 3. Instalar dependências Python

```bash
pip install -r requirements.txt
```

---

## Uso

```bash
python editor_agent.py
```

O programa carrega o modelo e inicia um loop de conversa. Digite comandos em português:

### Exemplos de comandos

| Comando | O que faz |
|---------|-----------|
| `Analise o vídeo C:/Videos/meu_video.mp4` | Mostra duração, resolução, codec, fps, etc. |
| `Corte o vídeo video.mp4 do 00:01:00 até 00:03:30` | Extrai um segmento do vídeo |
| `Corte o vídeo aula.mp4 começando em 00:05:00 com duração de 2 minutos` | Corte por início + duração |
| `Crie uma thumbnail do vídeo vlog.mp4 aos 10 segundos` | Gera uma imagem JPG de capa |
| `Otimize o vídeo final.mp4 para o YouTube` | Converte para H.264 1080p com faststart |
| `Otimize o vídeo final.mp4 para YouTube em 720p` | Otimiza em resolução 1280x720 |
| `Remova os silêncios do vídeo podcast.mp4` | Corta pausas longas automaticamente |
| `Extraia o áudio do vídeo musica.mp4` | Gera arquivo MP3 192kbps |

### Comandos do programa

- `ajuda` — Mostra exemplos de uso
- `sair` / `exit` / `quit` — Encerra o programa

---

## Estrutura

```
editor-video/
├── youtube_editor_tools.py   # Ferramentas FFmpeg (inspecionar, cortar, thumbnail, etc.)
├── editor_agent.py           # Agente principal com loop de conversa (LM Studio)
├── requirements.txt          # Dependências Python
├── README.md                 # Este arquivo
└── output/                   # Pasta gerada automaticamente com os arquivos editados
    ├── video_cortado.mp4
    ├── video_youtube.mp4
    ├── video_capa.jpg
    ├── video_audio.mp3
    └── ...
```

---

## Como funciona

1. O `editor_agent.py` carrega um modelo no LM Studio via SDK Python (`import lmstudio as lms`)
2. As ferramentas em `youtube_editor_tools.py` são funções Python com docstrings
3. O LM Studio lê as docstrings e decide qual ferramenta chamar baseado na sua pergunta
4. O método `.act()` executa o loop de tool calling automaticamente
5. Cada ferramenta chama o FFmpeg via `subprocess` e retorna o resultado
6. Os arquivos editados são salvos na pasta `./output/`

---

## Configurando

### Trocar o modelo

Edite a variável `MODEL_NAME` no topo do `editor_agent.py`:

```python
MODEL_NAME = "qwen2.5-14b-instruct"  # Ou qualquer modelo carregado no LM Studio
```

### Trocar a pasta de saída

Edite a variável `OUTPUT_DIR` no topo do `youtube_editor_tools.py`:

```python
OUTPUT_DIR = Path("./meus_videos_editados")
```

---

## Expansão

Para adicionar novas ferramentas:

1. Crie a função em `youtube_editor_tools.py` com type hints e docstring clara
2. A docstring é o que a IA usa para entender quando e como usar a ferramenta
3. Importe e adicione na lista `tools` no `editor_agent.py`

```python
# Exemplo de nova ferramenta
def adicionar_marca_dagua(video_path: str, imagem_path: str) -> str:
    """
    Adiciona uma marca d'água (imagem) sobre o vídeo.

    Args:
        video_path: Caminho do vídeo
        imagem_path: Caminho da imagem da marca d'água (PNG com transparência)

    Returns:
        str: Mensagem de sucesso ou erro
    """
    # ... implementação com FFmpeg
```

---

## Troubleshooting

**"FFmpeg não encontrado"**
- Verifique que o FFmpeg está instalado: `ffmpeg -version`
- Confirme que está no PATH do sistema

**"Erro ao carregar modelo"**
- Verifique que o LM Studio está rodando
- Confirme que o modelo está carregado (aparece na lista do LM Studio)
- Teste: `lms lm list` para ver modelos disponíveis

**"O modelo não chama as ferramentas"**
- Use modelos com bom suporte a tool calling (Qwen 2.5, Llama 3.3)
- Seja específico nos comandos: "Corte o vídeo X do tempo A até o tempo B"
