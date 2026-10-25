---
name: tutorial-editing
title: Edição de Tutoriais
description: Tutoriais com títulos de passo, pausas de leitura, aceleramento constante em esperas e capítulos por marcadores; sem zoom animado.
triggers: tutorial, passo a passo, como fazer, captura de tela, aula, instrucional, espera, capítulo
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, duplicate_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Quando usar
- Aulas de software, código, ferramenta ou processo com captura de tela.
- Narração falada mista com screencast; o público precisa acompanhar e repetir.
- Não use para entretenimento veloz (`short-form-vertical`) nem documental (`documentary-editing`).

## 2. Objetivo
Ensinar uma tarefa com passos numerados, ritmo que dá tempo de agir entre cliques, aceleramento honesto das esperas e lista de capítulos. `analyze_timeline_clip` mede transições de tela, pausas da narração e o nível de um clipe; não transcreve nem lê o que aparece na tela, então o sentido de cada passo vem do roteiro/timecodes do usuário.

## 3. Entradas necessárias
- Screencast/câmera com caminhos absolutos e o roteiro ou lista de passos.
- Esperas a acelerar (instalação, render) e erros a cortar: os tempos saem do usuário ou da medição (`kind="silence"`, `kind="scenes"`), nunca de suposição.
- Nome de cada passo e, se houver, legenda `.srt` externa.
- Resolução: 1920x1080@30; 60 apenas com captura de ação real.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `add_timeline_subtitles`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `duplicate_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`, `analyze_timeline_clip`, `clear_timeline_annotations`.

## 5. Fluxo passo a passo
1. Monte `v1` na ordem dos passos (sem `start`, o clipe entra no fim da faixa; `in_point`/`out_point` são do arquivo).
2. Meça as fronteiras, um clipe por vez: `analyze_timeline_clip(kind="scenes", threshold=15)` devolve cada transição de tela com score e com o tempo de timeline e o de arquivo — são as candidatas a fim de passo; `analyze_timeline_clip(kind="silence", noise=-35, min_pause=1.2)` acha a pausa de leitura e o "espero você clicar"; `analyze_timeline_clip(kind="loudness")` dá LUFS integrado, LRA e true peak daquela janela.
3. Reveja antes de agir: `apply_candidates=true` grava as cenas como marcadores `cenas` e as pausas como regiões `pausas`, num único passo de undo, visíveis na régua e no inspetor; `clear_timeline_annotations(group="pausas")` limpa o grupo para reanalisar com outro `min_pause`. Nada disso corta — `trim_timeline_clip`/`split_timeline_clip`/`delete_timeline_clip` vêm depois do aval.
4. Um passo por bloco de 5–20 s, com 0,5–1 s de respiro antes e depois de cada clique; corte erros com `split_timeline_clip` + `delete_timeline_clip(confirm=true, ripple=true)`.
5. Acelere esperas: use o início e o fim da região `pausas` (ou o tempo que o usuário deu), divida o trecho e `set_timeline_clip(speed=2 a 8)`; duração na timeline = (out-in)/speed; reinspecione colisões e zere o volume se houver narração por cima.
6. "Zoom" para ler botões: sem keyframes, use `transform_scale` constante (1,3–2,0) com `transform_x/transform_y` no clipe do detalhe; é recorte fixo, não animação — avise.
7. Título por passo em `t1`: "Passo 3 — Instalar", 3–6 s, 48–64 px, `position="topo"`, 2 linhas.
8. Capítulos: `add_timeline_marker` na fronteira de passo indicada pelas cenas medidas; copie a lista na resposta, marcadores não exportam.
9. Acessibilidade: `add_timeline_subtitles` com `.srt` do usuário, fonte 20–24, `margin_v=42`.
10. Narração `volume=1,0` a partir do LUFS medido; música 0,1–0,2 ou ausente; fades 0,5–1 s. Valide, prévia, confira o loudness no QC e exporte CRF 20–22.

## 6. Regras obrigatórias
- Nunca inventar passos, comandos ou atalhos: reproduza o roteiro e aponte divergências.
- Candidato medido não é corte nem passo: os tempos de `analyze_timeline_clip` viram marcadores `cenas` ou regiões `pausas` para revisão; quem corta é o `split`/`trim`/`delete`, depois do aval.
- Ao mudar `speed`, o áudio estica: abaixe ou zere o volume do trecho acelerado.
- `transform_scale` vale para o clipe inteiro; para outro enquadramento, duplique e ajuste o novo.
- Não prometer cursor destacado, setas nem zoom animado: não existem.

## 7. Critérios de qualidade
- Todo passo reproduzível por quem assistiu uma vez.
- Títulos legíveis no topo, sem cobrir a área usada; capítulos listados na resposta.
- Pausas de leitura presentes; espera acelerada com aviso na tela ("aguarde…").
- QC: loudness -14 ±2 LUFS, pico ≤ -1 dBTP, 16:9, fps coerente, `qc.ok=true`.

## 8. Erros comuns
- Jump cut a cada suspiro: o passo fica instantâneo e não dá tempo de agir; em tutorial `min_pause` fica em 1,2 s ou mais.
- Cortar clique e resultado colados: perde-se a relação causa/efeito.
- Acelerar a narração junto com a tela e só descobrir no export.
- Entregar `transform_scale` fixo sem explicar que não há zoom animado.
- Presumir transcrição ou legenda automática para achar os passos.

## 9. Limitações do sistema atual
`analyze_timeline_clip` roda FFmpeg num clipe da timeline e devolve medida, não decisão: `kind="scenes"` (scdet) traz as transições de tela com score, `threshold` de 1 a 100 (menor acha mais), cada uma com o tempo de timeline e o de arquivo; `kind="silence"` (silencedetect) traz início e fim de cada pausa conforme `noise` em dB e `min_pause` em s; `kind="loudness"` (ebur128) traz três números daquela janela — LUFS integrado, LRA em LU e true peak em dBFS — e não escreve nada. Com `apply_candidates=true` as cenas viram marcadores (`cenas`) e as pausas viram regiões (`pausas`) num passo de undo: o que foi feito à mão fica, duplicado é ignorado, acima de 400 candidatos a gravação falha e `clear_timeline_annotations` limpa só o grupo. A análise não corta; cortam `trim_timeline_clip`/`split_timeline_clip`/`delete_timeline_clip`, depois do aval. Não há transcrição, leitura do que aparece na tela, rastreamento de cursor, setas/callouts/formas, destaque de clique, curva de áudio por instante nem forma de onda, detecção de beat, zoom com keyframe, LUTs, multicam, ducking nem normalização de loudness — tirar a pausa continua sendo corte manual. Velocidade é constante (0,1–8, sem rampa), transição é só fade, cor é eq básico e títulos são estáticos. Compense com medição + roteiro do usuário e declare essas escolhas na resposta.

## 10. Exemplo de uso
Usuário: "Em `aula.mp4`, a instalação espera entre 04:10 e 09:30; acelere e titule os 4 passos."
1. Confirme a espera medindo: `analyze_timeline_clip(project_id=..., clip_id=..., kind="silence", noise=-35, min_pause=1.2, apply_candidates=true)` grava como região `pausas` o trecho que cobre a espera; `clear_timeline_annotations(group="pausas")` se os parâmetros não servirem.
2. `split_timeline_clip(clip_id=..., at=250)` e `at=570` para isolar a espera, nos tempos medidos e com aval.
3. `set_timeline_clip(clip_id=<meio>, speed=6, volume=0)` → 320 s viram ~53 s; reinspecione.
4. `add_timeline_text(text="Aguardando instalação…", start=250, duration=4, font_size=52, position="topo")`.
5. Títulos "Passo 1…4" com `add_timeline_text` e `add_timeline_marker` em cada fronteira, partindo das cenas medidas por `kind="scenes"`.
6. Narração: confira `kind="loudness"` por clipe antes de ajustar `volume`. `validate_timeline` → prévia → exporte. Responda com a lista de capítulos e avise: aceleramento constante, sem rampa, áudio mutado no trecho e passos definidos pelo roteiro do usuário.
