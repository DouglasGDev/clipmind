---
name: short-form-vertical
title: Vídeos curtos verticais
description: Fluxo 9:16 para Shorts, Reels e TikTok com gancho, ritmo, legendas e enquadramento manual sem auto-reframe.
triggers: shorts, reels, tiktok, vertical, 9:16, 1080x1920, vídeo curto, hook, legendas
tools: create_edit_project, inspect_edit_project, configure_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Objetivo
Produzir vídeo vertical de 15–60 s com gancho nos primeiros 1–2 s, ritmo de corte, legendas grandes e enquadramento planejado. Saída: 1080x1920, MP4 H.264/AAC, com QC.

## 2. Quando usar
- Shorts, Reels, TikTok e stories verticais.
- Reaproveitamento de fonte horizontal apenas com corte por plano; não há auto-reframe nem tracking.
- Não use para conteúdo longo horizontal; nesse caso, `youtube-long-form`.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: resolução, fps, duração, faixas, ids e marcadores.
2. `validate_timeline`: erro bloqueia o render; aviso precisa ser corrigido.
3. Confirme a proporção da fonte; o resumo não mostra a resolução.
4. Escolha por plano: letterbox, corte com `transform_scale` ou reedição.
5. Defina gancho (1–2 s), payoff e duração final.

## 4. Procedimento
1. `create_edit_project(1080, 1920, fps=30)`; 60 fps só com fonte 60.
2. `add_timeline_clip(track="v1")`. Fonte 16:9 entra em 1080x608, com barras de ~656 px.
3. Para preencher, `set_timeline_clip(transform_scale=3.16)` cobre 1080x1920 e mostra ~31% da largura; ajuste `transform_x` em ±1.100 px e confira plano a plano.
4. Gancho na ação ou rosto; sem fade >0,2 s nos primeiros 2 s.
5. Duração 15–60 s (ideal 20–45). `split_timeline_clip` e `delete_timeline_clip(confirm=true, ripple=true)`; 1,5–3 s por plano, 6–12 cortes em 30 s.
6. Legendas `s1`: `.srt` manual, 9–11, `margin_v=55–65`, 2 linhas e 3–6 palavras; 10 ≈ 67 px e 60 ≈ 400 px.
7. Títulos `t1`: 64–88 px, 2 linhas, `topo`/`centro`, fundo; posições fixas.
8. Valide, prévia, `done`, exporte `preview=false`, CRF 20–22 (18–20 em movimento).

## 5. Critérios e parâmetros
- 1080x1920, 30/60 fps coerente com a fonte; 15–60 s.
- CRF 20–22 para fala, ~3–8 Mbps; 18–20 em alto movimento, até ~12 Mbps.
- Gancho nos primeiros 1–2 s, sem preto, logo ou fade longo.
- Áreas seguras: ~220 px no topo, ~420 px na base, ~120 px à direita; ação entre y=250 e y=1500.
- Legendas 9–11, 2 linhas, acima da UI inferior.
- Áudio -14 LUFS ±2; true peak ≤ -1 dBTP.

## 6. Erros comuns
- Letterbox de 656 px por descuido; decida entre barras, corte ou reedição.
- `transform_scale=1,78` não preenche 9:16 e corta as laterais.
- Escala 3,16 sem conferir o assunto remove ~68% da largura.
- Legenda 22 fica enorme; `margin_v=42` fica atrás da UI.
- Fade no gancho, vídeo >60 s ou fonte 30 em projeto 60.

## 7. Checklist de qualidade
- [ ] 1080x1920 e fps da fonte.
- [ ] Gancho nos primeiros 1–2 s.
- [ ] Duração 15–60 s.
- [ ] Planos de 1,5–3 s, sem corte no meio da ação.
- [ ] Legendas 9–11, 2 linhas, margem 55–65.
- [ ] Ação em área segura; áudio -14 ±2 LUFS.
- [ ] Validação e QC aprovados.

## 8. Validação objetiva
1. `validate_timeline` com `ok=true` e zero erros.
2. Prévia 360p: ~202x360. Confira proporção, duração, fps e áudio no QC.
3. `qc.ok=true` só indica ausência de erros; leia `qc.issues`.
4. Revise gancho, legenda e área segura; o QC não avalia enquadramento.
5. Exporte em 1080x1920, CRF 20–22; recheque dimensões e áudio.
6. Entrega local, sem upload nem preset.

## 9. Limitações atuais do ClipMind
Não há auto-reframe, tracking, corte automático, transcrição nem legendas automáticas. O enquadramento é manual, com escala/deslocamento fixos por clipe. Sem keyframes, curvas de velocidade, fundo desfocado, LUTs ou presets; a prévia é 360p e não há upload. Alternativas: cortar por plano com `transform_scale`/`transform_x`, aceitar letterbox planejado ou reeditar em 9:16; escreva as legendas fora e importe `.srt`.

## 10. Ferramentas e skills relacionadas
- Projeto/montagem: `create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `set_timeline_clip`.
- Texto/entrega: `add_timeline_text`, `add_timeline_subtitles`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Skills: `youtube-long-form`, `tutorial-editing`, `gaming-video-editing`, `video-editor-core`.
