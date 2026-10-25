---
name: youtube-long-form
title: YouTube em formato longo
description: Estrutura, ritmo e exportação 16:9 para vídeos longos no YouTube, com capítulos manuais e QC.
triggers: youtube, vídeo longo, 16:9, 1080p, 4K, retenção, capítulos, thumbnail, horizontal
tools: create_edit_project, inspect_edit_project, configure_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, split_timeline_clip, delete_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Objetivo
Produzir vídeo horizontal de 3–60 min com gancho, introdução curta, corpo em blocos, CTA e final limpo. Saída: MP4 H.264/AAC na resolução do projeto com QC; upload, capa e tela final ficam fora.

## 2. Quando usar
- Entrevista, ensaio, aula, análise, gameplay longo ou vlog em 16:9.
- Fonte horizontal.
- Não use para Shorts/Reels (`short-form-vertical`); fonte vertical ganha faixas laterais, sem reenquadramento automático.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: resolução, fps, duração, faixas, ids e marcadores.
2. `validate_timeline`: erro bloqueia o render; aviso precisa ser corrigido.
3. Confirme resolução/fps das fontes; o resumo não mostra codec/fps.
4. `analyze_timeline_clip(kind="scenes", threshold=15)` clipe a clipe: cada troca de cena volta com score e com o tempo de timeline e o de arquivo; `threshold` menor acha mais. São os pontos de capítulo candidatos.
5. `analyze_timeline_clip(kind="silence", noise=-30, min_pause=0.6)` traz início e fim de cada pausa; `kind="loudness"` dá LUFS integrado, LRA e true peak daquela janela antes de mexer no `volume`.
6. Defina gancho (0–15 s), introdução, blocos, CTA e capítulos sobre o que a medição apontou.
7. `no_audio` na validação indica vídeo mudo. Sem transcrição: o assunto de cada bloco e o título dos capítulos continuam vindo do usuário.

## 4. Procedimento
1. `create_edit_project(width=1920, height=1080, fps=30)`; 60 fps e 4K só com fonte equivalente.
2. `add_timeline_clip(track="v1")`; sem `start`, entra no fim; `in`/`out` no tempo do arquivo.
3. Blocos de 2–4 min. `split_timeline_clip(at=...)` na fronteira medida; a pausa aprovada do grupo `pausas` sai com `split` + `delete_timeline_clip(confirm=true, ripple=true)`.
4. Capítulos: `analyze_timeline_clip(kind="scenes", threshold=15, apply_candidates=true)` grava a sugestão como marcadores do grupo `cenas`, num único passo de undo; revise na régua e no inspetor, descarte com `clear_timeline_annotations(group="cenas")`. Aprovados, fixe com `add_timeline_marker`: 3+, 00:00, ≥10 s, e copie os tempos — nada é enviado ao YouTube.
5. Títulos `t1`: 3–6 s, 2 linhas, 48–64 px, fundo; quebra manual.
6. Legendas `s1`: `.srt`/`.vtt`/`.ass`, 20–24, `margin_v=42`; queimadas.
7. Fades 0,5–1 s início, 1–2 s fim, 0,2–0,4 s entre blocos; ≤ metade do clipe; sem crossfade.
8. Meça `analyze_timeline_clip(kind="loudness")` por clipe antes de calcular `volume`; valide, prévia, `status=done`, exporte `preview=false`, CRF 18–20.

## 5. Critérios e parâmetros
- 1080p30: CRF 18–20 (~4–10 Mbps); 1080p60: 18–20 (8–16); 4K30: 20–22 (25–50); 4K60: 18–20 (40–80).
- 30 fps para fala/tutorial; 60 para gameplay; 24 só com fonte 24.
- Áudio: -14 LUFS ±2; true peak ≤ -1 dBTP.
- Planos de 3–8 s, mudança a cada 20–40 s; introdução >45 s custa retenção.
- Tela final: 15–20 s finais com o lado direito limpo.

## 6. Erros comuns
- 60 fps com fonte 30 duplica movimento.
- 1080p como 4K: arquivo maior sem detalhe.
- CRF 16 em talking head desperdiça espaço; 24 gera banding.
- Gancho atrás de logo ou introdução longa.
- Fade em todo corte pisca preto; use corte seco ou `v2`.
- Sobrepor na mesma faixa, capítulo sem 00:00 ou QC ignorado.

## 7. Checklist de qualidade
- [ ] 16:9 com resolução e fps da fonte.
- [ ] Gancho ≤15 s; introdução ≤45 s.
- [ ] Capítulos 3+, 00:00, ≥10 s.
- [ ] Títulos e legendas legíveis e sincronizados.
- [ ] Áudio -14 ±2 LUFS, pico ≤ -1 dBTP.
- [ ] Sem preto ≥0,5 s não intencional.
- [ ] Validação sem erros; prévia e export aprovados.

## 8. Validação objetiva
1. `validate_timeline` com `ok=true`; depois prévia 360p e `check_render_job` até `status=done` (640x360 em 16:9), conferindo dimensões, duração, fps e áudio.
2. `qc.ok=true` só indica ausência de erros; leia `qc.issues` (loudness, preto, sincronia).
3. Confira na prévia texto, legendas e tela final; o QC não vê isso.
4. Exporte com `preview=false`, CRF 18–20; recheque resolução, duração e áudio. Taxa = `size×8÷duration÷1e6` Mbps; se alta, +1–2 CRF.
5. Capítulos copiados à mão; entrega local.

## 9. Limitações atuais do ClipMind
`analyze_timeline_clip` mede um clipe da timeline com FFmpeg e devolve número, não decisão: `kind="scenes"` (scdet) traz as trocas de cena com score e tempo de timeline e de arquivo, `threshold` 1–100 (menor acha mais); `kind="silence"` (silencedetect) traz início e fim de cada pausa conforme `noise` em dB e `min_pause` em s; `kind="loudness"` (ebur128) traz três números daquela janela — LUFS integrado, LRA em LU, true peak em dBFS — sem curva de áudio por instante e sem forma de onda. Não corta nada: com `apply_candidates=true` as cenas viram marcadores do grupo `cenas` e as pausas, regiões do grupo `pausas`, num passo de undo, para o humano revisar e limpar com `clear_timeline_annotations`; o corte é `split_timeline_clip` + `delete_timeline_clip` depois do aval. Capítulos continuam manuais: nada é enviado ao YouTube e o texto vem do usuário, porque não há transcrição nem legenda automática. Sem thumbnail nem preset de upload; produza fora. O QC mede, não normaliza: ajuste `volume` por clipe (de -18 para -14, ×1,58). Sem keyframes, LUTs, curvas de velocidade, ducking, beat detection, multicam, rastreamento ou auto-reframe. Só fade, sem crossfade. Para vertical, use `short-form-vertical`.

## 10. Ferramentas e skills relacionadas
- Projeto/montagem: `create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `set_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`.
- Acabamento/entrega: `add_timeline_text`, `add_timeline_subtitles`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Análise: `analyze_timeline_clip`, `clear_timeline_annotations` (grava e limpa os candidatos `cenas`/`pausas`).
- Skills: `short-form-vertical`, `tutorial-editing`, `gaming-video-editing`, `podcast-editing`.
