# Roadmap — evoluir para um editor de vídeo profissional com LLM local

Auditoria e plano do ClipMind. Tudo abaixo está ancorado no que existe no
repositório hoje; nada é prometido como pronto sem teste que comprove.

Data da auditoria: 2026-10-24. Atualizada em 2026-10-25 com a análise de conteúdo.

---

## 1. Auditoria do estado atual

### 1.1 O que já funciona (com evidência)

| Área | Implementação | Evidência |
| --- | --- | --- |
| Modelo de projeto | JSON versionado (`schema`), escrita atômica, autosave, 30 snapshots por projeto, lixeira na exclusão | `editor_project.py` (`ProjectStore`), `tests/test_project_engine.py::test_persistencia_sobrevive_a_releitura` |
| Timeline não destrutiva | add/move/trim/split/delete/duplicate/slip/slide/roll + ripple, marcadores, regiões, anotação por grupo (`cenas`/`pausas`), faixas extras | `tests/test_project_engine.py` (82 testes) |
| Undo/redo transacional | `store.edit()` agrupa N mutações em um passo; falha no meio não deixa rastro; operação sem efeito não gasta passo nem versão | `test_um_edit_contexto_e_um_passo_de_undo`, `test_undo_nao_aparece_quando_edicao_falha`, `tests/test_api.py::test_operacao_sem_efeito_nao_consome_undo_nem_versao` |
| Validação | erros e avisos com `code`/`severity` (colisão, fora do arquivo, mídia ausente, fades, transição, sync) | `validate_project`, `test_valid_*` |
| Renderização multi-faixa | grafo único de `filter_complex` para vídeo sobreposto, títulos `drawtext`, legendas ASS próprias, mixagem de áudio, `atempo` em cadeia | `editor_render.py::_TimelineGraph`, `test_render_multicamadas_*` |
| Consistência prévia/export | mesma timeline, mesmo enquadramento; prévia só reduz altura | `test_export_e_preview_tem_mesma_duracao_e_proporcao` |
| Progresso, cancelamento, log | `-progress pipe:1`, percentual real, parcial apagado após matar o processo | `test_manager_cancela_e_apaga_o_parcial`, `test_cancel_antes_de_iniciar_nao_renderiza_nada` |
| QC pós-render | ffprobe + `blackdetect` + `ebur128` + delta de início A/V, separado em técnico vs estético | `validate_render`, `test_preview_renderiza_e_mediu_com_ffprobe` |
| Análise de conteúdo por clipe | trocas de cena (`scdet`), pausas (`silencedetect`) e LUFS/LRA/true peak (`ebur128`) medidos na janela do clipe, convertidos para tempo de timeline e de arquivo; candidatos viram marcadores/regiões num único undo e nada é cortado pela análise | `editor_analysis.py`, `tests/test_analysis.py` (54 testes), `tests/test_analysis_agent.py` (12 testes) |
| Codecs e containers | libx264/libx265/VP9, NVENC quando existir, `faststart`, CRF/preset/audio bitrate validados | `_encoder_args`, `test_encoder_args_*` |
| Legendas | SRT/VTT/ASS parseados, posição (inferior/centro/topo), margem, fonte, cor validadas, queima verificada quadro a quadro | `_write_subtitle_ass`, `test_write_subtitle_ass_*` |
| Títulos | texto, tamanho, cor, posição, fundo | `add_text_clip`, `test_subtitle_position_*` |
| IA com tool calling real | `lmstudio` SDK, `llm.act(chat, TOOLS)`, 21 ferramentas (incluindo `analyze_timeline_clip` e `clear_timeline_annotations`), histórico por projeto, timeout de turno | `timeline_agent.py`, `tests/test_timeline_agent.py` (67 testes, LM Studio simulado) + `tests/test_analysis_agent.py` |
| Skills | 21 skills × 10 seções obrigatórias, catálogo no prompt, carga sob demanda, ferramentas conferidas contra `TOOLS` | `editor_skills.py`, `tests/test_skills.py` (360 testes) |
| API HTTP do editor | `/api/editor/*` com 22 operações, rota `/analyze`, undo/redo, versões, render, filas, QC, mídia, skills e chat; 400/404/409 sem vazar traceback | `editor_api.py`, `tests/test_api.py` (83 testes), `tests/test_analysis.py` (rota `/analyze`) |
| Interface | `/editor` com timeline multifaixa, monitores, inspetor, painel de mídia, render, chat com eventos ao vivo; regiões visíveis e criáveis por entrada/saída, bloco **Análise** no inspetor; `/` clássico preservado | `templates/editor.html`, `static/editor.js` |
| Ferramentas de arquivo único | 23 operações FFmpeg (cena, silêncio, thumbnail, contact sheet, shorts, loudness, GIF…) | `youtube_editor_tools.py` |

### 1.2 O que NÃO existe e é exigido pelo objetivo

Transcrição com timestamps de palavra, edição pelo texto, curva de pico de
áudio por instante, corte automático a partir da medição (a análise hoje só
propõe candidatos), keyframes de verdade, áudio profissional (EQ, compressor,
limiter ajustável, de-esser, NR, ducking, automação, normalização para um alvo),
LUTs e scopes, correção vs. gradação separadas, auto-reframe com rastreamento,
sincronismo multicâmera, presets por plataforma, legendas com destaque palavra
a palavra, fila de render com retomada, proxies e aceleração por hardware
selecionada automaticamente.

A IA já mede *onde* estão as fronteiras (cenas, pausas) e *como* está o nível do
clipe (LUFS/LRA/true peak) antes de cortar. O que falta é saber *o que é dito* —
sem transcrição, o sentido continua vindo do humano — e agir sobre o áudio e a
imagem além de volume, fade e `eq` por clipe.

---

## 2. Regras de execução (válidas em todas as fases)

1. Inspecionar antes de editar; nenhuma função nova nasce duplicando outra.
2. Passo pequeno, verificável, com teste no mesmo passo.
3. Nada de botão decorativo, stub ou "por enquanto está assim".
4. Marcar como pendente o que não foi testado; implemented ≠ experimental ≠ planejado.
5. A IA só chama ferramentas controladas. Nenhum caminho aceita comando livre de FFmpeg.
6. O editor continua 100% utilizável sem LM Studio ligado.

---

## 3. Fase 1 — fechar o núcleo do editor (concluída nesta rodada)

- [x] Motor não destrutivo com ripple/roll/slip/slide, validação e undo.
- [x] Autosave, recuperação e versões em disco.
- [x] Renderizador multi-faixa com progresso, cancelamento, log e QC.
- [x] API REST + WebSocket e interface de editor.
- [x] 21 skills com as 10 seções obrigatórias e ferramentas verificadas.
- [x] Prévia separada da exportação final.
- [x] Suíte de testes do motor, do render, das skills, da API HTTP e do agente.

**Critério de aceite:** `python -m pytest tests -q` verde; um projeto real
editado pela IA renderiza e o QC não aponta erro técnico. *Cumprido em
2026-10-24: 641 testes passando e prévia de 6 s do projeto `p_cfbc64a86a`
renderizada com QC sem erro técnico (−21,3 LUFS, true peak −15,2 dBFS, delta
A/V 0,0).*

---

## 4. Fase 2 — a IA enxerga o conteúdo

| # | Entrega | Status | Aceite | Teste |
| --- | --- | --- | --- | --- |
| 2.1 | Transcrição local com timestamps de palavra (Whisper via LM Studio ou `faster-whisper`), gravada no projeto como `transcript` | **planejado** — exige instalar um ASR | projeto JSON guarda falas com início/fim; sem modelo, a ferramenta devolve erro claro e o editor segue usando | `test_transcript.py` |
| 2.2 | Edição pelo texto: seleccionar palavra → cortar; edição por transcrição é revisável e reversível (operação única no undo) | **planejado** — depende de 2.1 | cortar "aquele erro" remove exatamente o intervalo da fala e fecha o buraco | idem |
| 2.3 | Detecção de cena dentro do projeto (marcadores candidatos, não cortes automáticos) | **concluído** | `scdet` com `threshold` 1–100, score por troca, tempo de timeline *e* de arquivo; no clipe de teste a cena sai em 2,0 s com score 15,6 | `tests/test_analysis.py` |
| 2.4 | Detecção de silêncio e de picos de áudio como regiões revisáveis | **parcial** — as pausas estão prontas; a curva de pico por instante não existe | limiar (`noise`) e duração (`min_pause`) configuráveis, pausas do teste em (2,0–4,0) e (6,0–8,0); `loudness` mede LUFS/LRA/true peak do clipe; nada é apagado sem aprovação | `tests/test_analysis.py` |
| 2.5 | Ferramenta expondo tudo ao agente | **concluído** — `analyze_timeline_clip` + `clear_timeline_annotations` | a IA lista pausas e cenas com os tempos, grava candidatos com `apply_candidates=true` e limpa o grupo; o prompt obriga a medir antes de propor corte | `tests/test_analysis_agent.py` |
| 2.6 | Candidatos visíveis e revisáveis na interface | **concluído** | regiões aparecem na faixa da timeline, o bloco **Análise** do inspetor mede, aplica e limpa sem LLM; snap encaixa nas bordas da região | `tests/test_analysis.py` (rota `/analyze`) + uso manual em `/editor` |

**Modelo extra necessário:** um ASR (Whisper `large-v3` ou um modelo menor)
instalado no LM Studio para 2.1 e 2.2. Sem modelo carregado, a fase degrada com
aviso explícito — nunca com transcrição inventada. Nada instalado hoje.

---

## 5. Fase 3 — áudio e cor de verdade

- **3.1 Diagnóstico antes do processamento:** medir LUFS integrated/short-term,
  true peak, CLF, ruído de fundo e histograma *antes* de aplicar qualquer filtro.
- **3.2 Cadeia por clipe e por faixa:** highpass, lowpass, EQ paramétrico,
  compressor, limiter, de-esser, reduction de sala, ganho e automação
  (volumetric keyframes), crossfade entre clipes adjacentes, ducking da trilha
  sob a fala com alvo e range configuráveis.
- **3.3 Loudness alvo por destino** (YouTube −14 LUFS, podcast −16, cinema −20
  etc.), sem número universal escondido no código.
- **3.4 Cor separada em correção e gradação:** exposição, contraste, temperatura,
  matiz, saturação, gama, sombras/médios/altos, curvas, correção seletiva por
  matiz, LUT `.cube`, casamento de plano e scopes (waveform/vectorscope/histograma)
  calculados do render real.
- **3.5 Sem valor inventado:** a IA não declara "ISO" nem "wb 5600K" que o
  arquivo não tem; trabalha com as medidas do render.

Aceite: cada filtro produz diferença mensurável no QC (LUFS antes/depois,
distribuição de histograma) e cada um é reversível com um undo.

---

## 6. Fase 4 — formatos, títulos e plataformas

- **4.1 Presets por plataforma** (YouTube longo 16:9 com capítulos e thumbnail,
  Shorts/Reels/TikTok 9:16 com área segura, podcast/entrevista multicâmera):
  resolução, fps, bitrate, loudness, legenda e marca d'água vêm do preset, não
  de constantes soltas na exportação.
- **4.2 Reenquadramento inteligente:** recorte guiado por rastreamento quando
  existir modelo; caso contrário, modo assistido (o usuário arrasta, a IA
  sugere) **declarando** que não há rastreamento. Sem alegação falsa.
- **4.3 Títulos e motion graphics:** templates, lower thirds, entradas/saídas,
  realce de palavra na legenda e gráficos reutilizáveis exportáveis como
  overlay alfa.
- **4.4 Legendas:** edição com sincronização por linha, quebra de linha
  inteligente, margens seguras, embutidas no container e também em `.srt`
  separado.

---

## 7. Fase 5 — robustez de produção

- Fila de render com prioridade, retomada após queda e limite de concorrência.
- Proxies automáticos (gerar media de working, trocar na prévia, usar original
  na exportação).
- Aceleração de hardware detectada e escolhida por capacidade real, com fallback
  por CPU.
- Cache de análise (cenas, loudness, transcrição) invalidado por hash do
  arquivo + parâmetros.
- Monitoração de memória, limpeza de temporários e verificação de integridade
  da mídia na abertura do projeto.
- Relatórios de QC armazenados por versão para comparação antes/depois.

---

## 8. Limitações conhecidas hoje (ditas sem maquiagem)

- **Keyframes não existem.** Transform, cor e velocidade são constantes por
  clipe; "animação" hoje é dividir em segmentos com valores diferentes (degraus
  visíveis, sem easing).
- **Transição é só fade.** Nenhum wipe/dissolve direcional.
- **Cor é `eq` básico** (brilho, contraste, saturação, gama). Não há curvas,
  LUT nem scopes.
- **Áudio é volume + fade.** Não há EQ, compressor, limiter, NR nem ducking.
- **Não há transcrição.** A IA mede o conteúdo (onde viram as cenas, onde estão
  as pausas, como está o nível) mas não sabe o que é dito: texto e sentido
  continuam vindo do humano.
- **Análise não tem cache.** Cada `analyze_timeline_clip` roda FFmpeg no arquivo
  de novo; dez minutos de `silencedetect` custam segundos. A fila de Fase 5
  previsto (hash do arquivo + parâmetros) ainda não existe.
- **Título é estático** (`drawtext`), sem entrada/saída animada.
- **Undo/redo vive em memória da sessão**; o que sobrevive ao reiniciar são as
  versões em disco.
- **Upload do navegador grava em `./uploads` sem validar tamanho nem tipo** (o
  filtro `accept` é só da interface) e o editor continua capaz de abrir caminho
  absoluto da máquina onde o servidor roda — é um editor local, não um serviço
  multiusuário.
- **Modelo local (27B em GPU AMD) leva 60–120 s por rodada.** Fluxos com muitas
  rodadas estouram timeouts; por isso as etapas obrigatórias do prompt são
  condicionais e o turno tem teto configurável (`CLIPMIND_TURN_TIMEOUT`).

---

## 9. Como continuar

1. Transcrição (2.1) é o único item da fase 2 travado por dependência externa:
   exige instalar um ASR no LM Studio, decisão do usuário. Sem ela, 2.2 não
   existe. Os outros caminhos abertos são a curva de pico por instante (fechar
   2.4) e a fase 3.
2. Antes de mexer no renderizador, rode `python -m pytest tests -q` e mantenha
   verde; o render tem testes com FFmpeg real que pegam regressão de janela de
   legenda, sync A/V e cancelamento.
3. Toda ferramenta nova para a IA entra em `timeline_agent.py`, é adicionada à
   lista `TOOLS` e só então é citada em `tools:` das skills — `test_skills.py` e
   `test_timeline_agent.py::NOMES_ESPERADOS` recusam nome inventado.
4. Toda medição nova de áudio entra com a janela recortada em `atrim`/`asetpts`
   dentro do filtro, nunca com `-ss` na entrada, e é conferida contra um número
   real do material de teste.
5. Atualize `docs/PROGRESSO.md` a cada passo concluído.
