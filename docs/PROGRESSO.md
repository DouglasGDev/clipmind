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

- **Curva de pico de áudio por instante** (`editor_analysis.py`, `kind="peaks"`):
  `astats` mede o pico de cada quadro de áudio (≈21 ms a 48 kHz) na janela do
  clipe, recortada com `atrim`/`asetpts` dentro de `-af` — a mesma regra do
  loudness, nunca `-ss` na entrada. `peak_curve` agrupa os quadros por intervalo
  (padrão 0,1 s) guardando o pico de cada faixa, devolve `null` no silêncio
  digital em vez de inventar número e limita a curva a **600 pontos** (o intervalo
  efetivo sobe sozinho em clipes longos). No fixture, o primeiro quadro mede
  **+3,92 dBFS**, o tom contínuo **−0,45 dBFS** e os trechos de 2,0 s e 6,0 s
  voltam `null`.
- **Picos como candidatos revisáveis** (`find_peaks`): mediana dos trechos
  audíveis (acima de −60 dBFS), limite = mediana + `rise` (0–40 dB, padrão 6),
  cada trecho contíguo acima do limite vira um candidato no seu ponto mais alto
  com a duração do trecho, e `min_gap` (0,1–60 s, padrão 1 s) mantém o mais alto
  entre vizinhos. Tempo de timeline e de arquivo respeitam `in` e `speed`; o
  grupo é `picos`, o marcador é `#F97316` e o rótulo é `Pico 3.9 dBFS`.
- **Rota `/analyze`**: aceita `rise`, `min_gap` e `interval` além dos parâmetros
  já existentes; valor fora da faixa devolve 400. Com `apply=true` os picos
  entram num único passo de undo (`annotate`) e a resposta conta o que ficou no
  projeto depois da escrita.
- **Agente**: `analyze_timeline_clip` ganhou `rise` e `min_gap`; a resposta traz
  um resumo da curva (`intervalo_s`, `pontos`, `mediana_dbfs`, `limite_dbfs`) e,
  no máximo, 40 candidatos por chamada. O prompt de sistema lista `peaks` entre
  as medições obrigatórias antes de propor corte. As 21 ferramentas não mudaram
  de nome.
- **Interface**: a lista de análise ganhou **Picos de áudio**, com os campos
  `Acima da mediana (dB)` e `Distância mín. (s)` visíveis só nesse tipo. O painel
  desenha a curva em SVG (até 600 barras, linha tracejada do limite) e mantém os
  botões **Aplicar como candidatos** e **Limpar "picos"**.
- **Defeito pego na verificação ao vivo**: **Medir** recriava o inspetor antes de
  montar o pedido, e o `rise` digitado (3) era trocado pelo padrão (6) na
  releitura dos campos. Corrigido com `state.analysisParams`: os valores são
  lidos antes do re-render, guardados no estado e reaplicados no formulário. Na
  interface, `rise=3` passou a produzir “1 pico acima de 2.5 dBFS” e continuou
  `3` depois do resultado.
- **Status do agente quando o LM Studio exige token**: o ramo de falha de
  autenticação devolvia modelo vazio; passou a devolver `"(auto)"`, como o ramo
  desconectado. Nenhum token é lido ou gravado.
- **Skills**: 14 `SKILL.md` (vídeo, áudio, corte, render, acessibilidade, b-roll,
  documentário, games, podcast, short-form, storytelling, transições, tutorial e
  YouTube) citam `kind="peaks"`, a curva no painel e a limpeza do grupo `picos`;
  a seção de limitações diferencia a curva de análise de uma waveform na
  timeline.
- **Docs**: README (curva no bloco Análise, `peaks`/`rise`/`min_gap`/`interval`
  na rota, 731 testes) e roadmap (2.4 concluído, 2.5/2.6 com picos, §9 apontando
  a Fase 3).

Total: **731 testes em 34 s** nesta execução (`python -m pytest tests -q`), sem
xfail e sem LM Studio; o único aviso é o de depreciação do Starlette/httpx na
própria biblioteca. Novos nesta rodada: `tests/test_analysis.py` 54 → 74 e
`tests/test_analysis_agent.py` 12 → 14.

Verificado no servidor real (`127.0.0.1:8011` com `CLIPMIND_PROJECTS`
descartável, sem tocar no servidor da porta 8000): projeto `p_39b343b1d5`, clipe
`c_d60f625a2c` de `video_com_pausas.mp4` (10 s). `/analyze` com
`kind="peaks", rise=3` devolveu **100 pontos a cada 0,1 s**, mediana
**−0,45 dBFS**, limite **2,55 dBFS**, primeiro ponto **+3,92 dBFS**, `null` em
2,0 s e 6,0 s e **1 candidato em 0,0** com rótulo `Pico 3.9 dBFS`. O `apply`
gravou 1 marcador do grupo `picos` (`#F97316`) gastando um único passo
(`annotate`); o undo removeu e a regravação trouxe de volta.

Na interface `/editor`, o clipe selecionado mostrou a opção **Picos de áudio**,
apenas os dois campos desse tipo, a curva desenhada em SVG (600×48, 62 barras
audíveis e a linha tracejada do limite) e a medição com `rise=3` resumida em
“1 pico(s) acima de 2.5 dBFS”. **Aplicar como candidatos** gravou o marcador e
**Limpar "picos"** removeu. O navegador embutido estava com viewport 0×0
(`visibilityState=hidden`): a verificação foi feita por eventos `pointerdown` e
chamadas da própria página, sem screenshot nem clique humano.

## Rodada anterior (2026-10-25 — análise de conteúdo)

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

Total daquela rodada: **709 testes em ~18 s**, sem xfail e sem LM Studio. Novos:
`tests/test_analysis.py` (54) e `tests/test_analysis_agent.py` (12).

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

- **Waveform na timeline e curva do projeto inteiro**: a curva existe no painel
  de análise, por clipe medido; não é uma faixa de waveform contínua e não tem
  cache.
- **Transcrição com timestamps (2.1)** e edição pelo texto (2.2): exige instalar um
  ASR no LM Studio, decisão do usuário. Nada instalado hoje.
- Validar tamanho e tipo do `POST /upload` no servidor (hoje o filtro é só o
  `accept` da interface) e listar os uploads por projeto.
- Fase 3: cadeia de áudio por faixa (EQ, compressor, limiter, ducking), cor com
  LUT/scopes e keyframes.
- Presets de plataforma e reenquadramento 9:16 assistido — Fase 4.
- Fila com retomada, cache de análise por hash do arquivo, proxies e aceleração por
  hardware — Fase 5.

## Limitações conhecidas

Ver seção 8 de `docs/ROADMAP_PROFESSIONAL_EDITOR.md` (keyframes, transições,
cor, áudio, transcrição, waveform, reenquadramento, undo em memória, custo de
cada medição, tempo do modelo local).
