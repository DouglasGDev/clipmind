---
name: audio-post-production
title: Pós-produção de áudio
description: Diagnostica loudness e picos, ajusta volumes, fades e equilíbrio entre fala e música sem clipping.
triggers: áudio, audio, loudness, LUFS, mixagem, volume, fade, sincronia, clipping, trilha
tools: inspect_edit_project, add_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, list_editor_skills, load_editor_skill
---

## 1. Objetivo
Mixagem inteligível: fala à frente, música sob controle, sem clipping e fades naturais. Meça, ajuste volume/fade por clipe e comprove no QC. EQ, compressão e normalização não existem no motor.

## 2. Quando usar
- Depois do lock, ao equilibrar fala, música e efeitos; ao corrigir pico, silêncio, LRA alto ou delta A/V.
- Antes da prévia e da exportação. Não serve para reparar ruído ou timbre.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: faixas, ids, tempos, volume, fades, velocidade e áudio de cada fonte.
2. Fala em `a1`, música em `a2`, efeitos em `a3`; música embutida no vídeo também precisa ser controlada.
3. Prévia (`preview=true`) + `check_render_job`: `loudness_lufs`, `lra_lu`, `true_peak_dbfs`, `av_start_delta`.
4. -14 LUFS para YouTube, não universal; -23 LUFS em broadcast. Confirme o destino.
5. Pico ≤ -1 dBTP; aviso acima de -0,1 dBFS; limitador fixo 0,95 (≈ -0,45 dBFS), não é alvo.
6. LRA 5–12 LU (>15 revisar); `audio_silence` < -60 LUFS; `av_start_delta` ≤ 0,15 s.

## 4. Procedimento
1. Faça a prévia de referência e anote os números antes de ajustar.
2. Faixas: música em `a2` via `add_timeline_clip`, efeitos em `a3`; não empilhe tudo em `a1`.
3. Fala em `volume=1.0`; use 1,2–1,5 se baixa e 0,7–0,9 se quente; teto 2,0 (+6 dB).
4. Música sob fala 0,12–0,25 (≈ -18 a -12 dB); sozinha 0,35–0,6; efeitos 0,2–0,6, abaixo da fala.
5. Fades com `set_timeline_clip`: fala 0,1–0,25 s in e 0,15–0,4 s out; música 0,5–2,0 s. `speed` 0,1–8 preserva o pitch; fala 0,9–1,1.
6. Prévia, números, um controle por vez, em passos de 1–2 dB (fator 0,89–1,12).
7. Marque, valide e exporte com `preview=false`; o QC final vale mais que a prévia 360p.

## 5. Critérios e parâmetros
- Fala: 0,9–1,3 (1,0 é âncora; 2,0 é teto prático).
- Música sob fala: 0,12–0,25 (≈ -18 a -12 dB); sozinha: 0,35–0,6.
- Efeitos: 0,2–0,6, com pico abaixo da fala.
- Fades: fala 0,1–0,4 s; música 0,5–2,0 s.
- Loudness: -14 LUFS ±1 para YouTube; pico ≤ -1 dBTP, com margem de 0,3–0,5 dB na exportação.
- LRA: 5–12 LU; acima de 15 LU, revisar.
Volume e fades são estáticos por clipe; o limitador não tem threshold ajustável e não há automação.

## 6. Erros comuns
- Normalizar de ouvido em vez de medir.
- Subir toda a fala em +6 dB: o ruído sobe e a mixagem achata.
- Deixar música em 0,5 sob diálogo; comece em 0,15.
- Fade de 1 s em frase curta: come palavras; use 0,15–0,25 s.
- Somar trilhas sem medir; a soma pode clipar.

## 7. Checklist de qualidade
- [ ] Fala à frente da música.
- [ ] Loudness na referência e pico ≤ -1 dBTP no QC final.
- [ ] Fades sem cortes de sílaba.
- [ ] Sincronia conferida no início, meio e fim.
- [ ] Marcadores e QC final registrados.

## 8. Validação objetiva
1. `validate_timeline` com `ok=true` e nenhum erro.
2. `check_render_job` com `status=done` e `qc.ok=true`; leia os avisos.
3. Loudness na referência, pico ≤ -1 dBTP, LRA 5–12 LU e `av_start_delta` ≤ 0,15 s.
4. Sem `audio_silence`, `audio_peak` nem `av_sync`; exporte e repita o QC, mantendo 0,3–0,5 dB de margem.
5. O agente não ouve: peça revisão humana de inteligibilidade, timbre e naturalidade dos fades.

## 9. Limitações atuais do ClipMind
- Não há normalização para LUFS alvo no editor; o QC apenas mede. Chegar a -14 LUFS exige iterar volume manualmente. `loudnorm` exigiria mudança de código.
- Não há EQ, compressão, de-esser, redução de ruído nem ducking por sidechain.
- O limitador é fixo em 0,95 (≈ -0,45 dBFS), sem threshold, release ou ceiling; não há automação de volume, keyframes, crossfade dedicado, waveform, correlação, espectro ou stems.
- Mute prático é `volume=0`; não há parâmetro dedicado de mute. FFmpeg externo não atualiza o projeto sem mudança de código.

## 10. Ferramentas e skills relacionadas
- Ajuste e validação: `inspect_edit_project`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Catálogo: `list_editor_skills`, `load_editor_skill`.
- Skills afins: `color-correction`, `color-grading`, `motion-graphics`, `subtitles-and-captions`.
