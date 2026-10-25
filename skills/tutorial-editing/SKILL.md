---
name: tutorial-editing
title: Edição de Tutoriais
description: Tutoriais com títulos de passo, pausas de leitura, aceleramento constante em esperas e capítulos por marcadores; sem zoom animado.
triggers: tutorial, passo a passo, como fazer, captura de tela, aula, instrucional, espera, capítulo
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, duplicate_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Quando usar
- Aulas de software, código, ferramenta ou processo com captura de tela.
- Narração falada mista com screencast; o público precisa acompanhar e repetir.
- Não use para entretenimento veloz (`short-form-vertical`) nem documental (`documentary-editing`).

## 2. Objetivo
Ensinar uma tarefa com passos numerados, ritmo que dá tempo de agir entre cliques, aceleramento honesto das esperas e lista de capítulos. Sem transcrição nem análise de tela, a estrutura vem do roteiro/timecodes do usuário; a IA executa.

## 3. Entradas necessárias
- Screencast/câmera com caminhos absolutos e o roteiro ou lista de passos.
- Timecodes das esperas a acelerar (instalação, render) e dos erros a cortar.
- Nome de cada passo e, se houver, legenda `.srt` externa.
- Resolução: 1920x1080@30; 60 apenas com captura de ação real.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `add_timeline_subtitles`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `duplicate_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.

## 5. Fluxo passo a passo
1. Monte `v1` na ordem dos passos (sem `start`, o clipe entra no fim da faixa; `in_point`/`out_point` são do arquivo).
2. Um passo por bloco de 5–20 s, com 0,5–1 s de respiro antes e depois de cada clique; corte erros com `split_timeline_clip` + `delete_timeline_clip(confirm=true, ripple=true)`.
3. Acelere esperas: divida o trecho e `set_timeline_clip(speed=2 a 8)`; duração na timeline = (out-in)/speed; reinspecione colisões e zere o volume se houver narração por cima.
4. "Zoom" para ler botões: sem keyframes, use `transform_scale` constante (1,3–2,0) com `transform_x/transform_y` no clipe do detalhe; é recorte fixo, não animação — avise.
5. Título por passo em `t1`: "Passo 3 — Instalar", 3–6 s, 48–64 px, `position="topo"`, 2 linhas.
6. Capítulos: `add_timeline_marker` por passo; copie a lista na resposta, marcadores não exportam.
7. Acessibilidade: `add_timeline_subtitles` com `.srt` do usuário, fonte 20–24, `margin_v=42`.
8. Narração `volume=1,0`; música 0,1–0,2 ou ausente; fades 0,5–1 s. Valide, prévia, confira loudness no QC e exporte CRF 20–22.

## 6. Regras obrigatórias
- Nunca inventar passos, comandos ou atalhos: reproduza o roteiro e aponte divergências.
- Ao mudar `speed`, o áudio estica: abaixe ou zere o volume do trecho acelerado.
- `transform_scale` vale para o clipe inteiro; para outro enquadramento, duplique e ajuste o novo.
- Não prometer cursor destacado, setas nem zoom animado: não existem.

## 7. Critérios de qualidade
- Todo passo reproduzível por quem assistiu uma vez.
- Títulos legíveis no topo, sem cobrir a área usada; capítulos listados na resposta.
- Pausas de leitura presentes; espera acelerada com aviso na tela ("aguarde…").
- QC: loudness -14 ±2 LUFS, pico ≤ -1 dBTP, 16:9, fps coerente, `qc.ok=true`.

## 8. Erros comuns
- Jump cut a cada suspiro: o passo fica instantâneo e não dá tempo de agir.
- Cortar clique e resultado colados: perde-se a relação causa/efeito.
- Acelerar a narração junto com a tela e só descobrir no export.
- Entregar `transform_scale` fixo sem explicar que não há zoom animado.
- Presumir transcrição ou legenda automática para achar os passos.

## 9. Limitações do sistema atual
Sem transcrição/Whisper, remoção de silêncio, detecção de cena, rastreamento de cursor, setas/callouts/formas, zoom com keyframe, LUTs, multicam, ducking e análise de conteúdo. Velocidade é constante (0,1–8, sem rampa), transição é só fade, cor é eq básico e títulos são estáticos. Compense com marcadores + timecodes do usuário e `transform_scale` fixo, declarando essas escolhas na resposta.

## 10. Exemplo de uso
Usuário: "Em `aula.mp4`, a instalação espera entre 04:10 e 09:30; acelere e titule os 4 passos."
1. `split_timeline_clip(clip_id=..., at=250)` e `at=570` para isolar a espera.
2. `set_timeline_clip(clip_id=<meio>, speed=6, volume=0)` → 320 s viram ~53 s; reinspecione.
3. `add_timeline_text(text="Aguardando instalação…", start=250, duration=4, font_size=52, position="topo")`.
4. Títulos "Passo 1…4" com `add_timeline_text` e `add_timeline_marker` em cada fronteira.
5. `validate_timeline` → prévia → exporte. Responda com a lista de capítulos e avise: aceleramento constante, sem rampa, e áudio mutado no trecho.
