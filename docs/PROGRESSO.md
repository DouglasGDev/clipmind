# Progresso do editor profissional

Arquivo de acompanhamento. **Feito** = testado; **experimental** = funciona no
fluxo feliz sem suíte de testes; **planejado** = não existe.

Última atualização: 2026-10-25.

## Como verificar

```bash
python -m pytest tests -q     # suíte completa (motor, render, análise, skills, API, agente)
python server.py              # / (ferramentas clássicas) e /editor (timeline)
```

## Feito nesta rodada

- **Análise de conteúdo por clipe** (`editor_analysis.py`): `scene_cuts` (`scdet`),
  `silence_ranges` (`silencedetect`) e `loudness` (`ebur128`) rodam FFmpeg na
  janela do clipe e os leitores de log viraram a fonte única de verdade — o QC do
  render (`editor_render.validate_render`) passou a usar os mesmos parsers em vez
  de manter regex próprio. Os tempos voltam em **tempo de timeline** e em tempo do
  arquivo, respeitando `in` e `speed`.
- **Candidatos gravados no projeto**: operações `annotate` e `clear_annotations`
  (e `remove_region`), um passo de undo por chamada, agrupadas em `cenas`/`pausas`.
  Reanalisar substitui só o próprio grupo, preservando marcadores e regiões feitos
  à mão; duplicados são pulados, mais de 400 candidatos são recusados e cor
  inválida vira erro em vez de branco silencioso. A análise **não corta nada**.
- **Rota `POST /api/editor/projects/{id}/analyze`** com o FFmpeg em
  `asyncio.to_thread` (o event loop serve o WebSocket da interface). Sem `apply`
  não grava nada; `apply` numa análise sem candidato devolve 400.
- **Interface** — regiões deixaram de ser invisíveis: faixa clicável na timeline
  (o clique leva o playhead ao início), painel de regiões com ir/remover, snap
  encaixando nas bordas das regiões, `I` marca entrada, `O` marca saída e `+` cria
  a região entre elas. O inspetor ganhou o bloco **Análise** (tipo, parâmetros
  por tipo, **Medir**, **Aplicar como candidatos**, **Limpar "grupo"**), que
  funciona sem LM Studio ligado.
- **Agente**: `analyze_timeline_clip` e `clear_timeline_annotations` entraram em
  `TOOLS` (19 → 21 ferramentas) e o prompt de sistema agora obriga a medir antes
  de propor corte. A resposta traz `grupo` para a IA saber o que limpar.
- **Defeito de medição corrigido na raiz**: o true peak saía 0,1 dBFS onde havia
  3,9 dBFS, porque `-ss` na entrada faz o FFmpeg descartar ~21 ms de priming do
  decodificador AAC antes do filtro. A janela de áudio passou a ser recortada com
  `atrim`/`asetpts` dentro de `-af`; confirmado decodificando o fixture para WAV e
  medindo a amostra de pico. Teste travado nos números reais (−4,6 LUFS, 3,0 LU,
  +3,9 dBFS) existe para a regressão não voltar.
- **Dois defeitos pegos pelos testes antes de qualquer commit**: `parse_black_log`
  devolvia faixa de preto com duração zero (parênteses redundantes deslocaram os
  índices dos grupos capturados) e `/analyze` com `apply` estourava
  `KeyError: 'markers'` porque `build_annotations` omitia uma das chaves conforme o
  tipo de análise.
- **Skills**: 16 `SKILL.md` atualizados — `tools:` com as duas ferramentas onde o
  método depende de medir, seção 9 reescrita para dizer o que é medido hoje e o que
  continua não existindo (transcrição, waveform, curva de pico por instante,
  filtros de áudio, LUT, scopes, rastreamento), e frases que afirmavam "não há
  detecção de silêncio/cena" foram corrigidas. `test_skills.py` recusa ferramenta
  inventada, e `accessibility-and-quality-control` ficou só com `analyze_timeline_clip`
  porque seu procedimento não grava candidatos.
- **Docs**: README (21 ferramentas do agente, 22 operações, rota `/analyze`,
  atalhos `I`/`O`, bloco Análise, `editor_analysis.py` na árvore, 709 testes) e
  roadmap (Fase 2 com status por item, §1.2 e §8 corrigidos, regras de continuação).

Total: **709 testes em ~18 s** (`python -m pytest tests -q`), sem xfail e sem
LM Studio. Novos: `tests/test_analysis.py` (54) e `tests/test_analysis_agent.py` (12).

Verificado na interface com o servidor real (`/editor`): no projeto
`p_cc3f9bd97c`, o clipe de `video_com_pausas.mp4` iniciado em 6 s devolveu as
pausas em **00:08 → 00:10** e **00:12 → 00:14** (`source_start` 2,0 e 6,0),
**Aplicar como candidatos** escreveu 2 regiões do grupo `pausas` (`#4F8CFF`)
gastando um único passo de undo (`annotate`), **Limpar "pausas"** zerou as faixas
e a regravação as trouxe de volta; clicar na faixa levou o playhead ao início da
região e `I`/`O`/`+` criaram uma região manual de 8 s a 12 s ao lado das medidas.
O loudness do mesmo clipe pela rota deu **−4,6 LUFS integrados, LRA 3,0 LU, true
peak +3,9 dBFS** — os mesmos três números que `tests/test_analysis.py` trava, agora
medidos pelo servidor de verdade, com o pico acima de 0 dBFS que o `-ss` na entrada
escondia.

## Rodada anterior (2026-10-24)

- **Suíte HTTP da API** (`tests/test_api.py`, 83 testes): criar/listar/ativar/apagar
  projeto, cada rota de operação, undo/redo, versões, validação, render, filas,
  cancelamento, QC, mídia, uploads, skills e chat — inclusive os códigos de erro.
- **Endurecimento da camada HTTP**: corpo malformado agora devolve 400 com
  mensagem em `detail` (antes podia virar 500); `create_project` recusa campo
  inesperado em vez de ignorar; e a separação 400/404 foi corrigida — id de
  projeto, clipe ou versão que não existe é recurso ausente, o resto é pedido
  inválido. Nenhuma resposta vaza traceback.
- **Operação sem efeito não consome undo nem versão** (`_assinatura` compara o
  estado ignorando `updated_at`/`recent_operations`).
- **Volume validado nas duas entradas** (`_valida_volume`): `add_clip` aceitava 9
  e `set_clip_properties` cortava em 4, contradizendo as docstrings que o modelo lê.
- **Suíte do agente da timeline** (`tests/test_timeline_agent.py`, 65 testes na
  época; 67 hoje): ferramentas congeladas por nome, varredura provando que todo id
  inexistente volta como `{"ok": false}`, rejeição de colisão/velocidade/volume/cor
  sem gastar undo, exclusão exigindo `confirm`, e o LM Studio **simulado** (ordem
  dos eventos, histórico por projeto, `reset_chat`, token mascarado, timeout de
  turno) com cliente falso.
- **README** com o editor profissional: fluxo, atalhos, endpoints, variáveis
  `CLIPMIND_PROJECTS` e `CLIPMIND_TURN_TIMEOUT`, árvore e seção de testes.
- **Motor e render cobertos por teste**: conversão de tempo/fps,
  add/move/trim/split/delete/duplicate/slip/slide/roll com ripple, colisões,
  velocidade, transform/cor com limites, transição, fades, marcadores, regiões,
  `validate_project`, undo/redo transacional, persistência, versões e restauração;
  render com QC por ffprobe/ebur128/blackdetect, prévia vs. export com mesma
  duração e proporção, cancelamento colhendo o processo no Windows e apagando o
  parcial (`tests/test_project_engine.py`, `tests/test_render.py`).
- **Skills**: 21 catálogos com as 10 seções obrigatórias em ordem, ferramentas
  conferidas contra `timeline_agent.TOOLS`, carga sob demanda com truncamento
  sinalizado (`tests/test_skills.py`).
- Cores deixaram de ser texto livre: `normalize_color` aceita `#RRGGBB`, `0xRRGGBB`
  e nomes PT/EN e devolve erro claro para o resto.

## Pendente (próxima rodada)

- **Curva de pico de áudio por instante** para fechar 2.4 do roadmap — hoje
  `loudness` devolve três números agregados do clipe, não onde o nível está alto.
- **Transcrição com timestamps (2.1)** e edição pelo texto (2.2): exige instalar um
  ASR no LM Studio, decisão do usuário. Nada instalado hoje.
- Validar tamanho e tipo do `POST /upload` no servidor (hoje o filtro é só o
  `accept` da interface) e listar os uploads por projeto.
- Keyframes, áudio por faixa (ducking, EQ, compressor) e LUTs — Fase 3.
- Presets de plataforma e reenquadramento 9:16 assistido — Fase 4.
- Fila com retomada, cache de análise por hash do arquivo, proxies e aceleração por
  hardware — Fase 5.

## Limitações conhecidas

Ver seção 8 de `docs/ROADMAP_PROFESSIONAL_EDITOR.md` (keyframes, transições,
cor, áudio, transcrição, reenquadramento, undo em memória, custo de cada medição,
tempo do modelo local).
