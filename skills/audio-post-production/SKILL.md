---
name: audio-post-production
title: Pós-produção de áudio
description: Diagnostica loudness e picos, ajusta volumes, fades e equilíbrio entre fala e música sem clipping.
triggers: áudio, audio, loudness, LUFS, mixagem, volume, fade, sincronia, clipping, trilha
tools: inspect_edit_project, add_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, list_editor_skills, load_editor_skill, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Objetivo
Mixagem inteligível: fala à frente, música sob controle, sem clipping e fades naturais. Meça, ajuste volume/fade por clipe e comprove no QC. EQ, compressão e normalização não existem no motor.

## 2. Quando usar
- Depois do lock, ao equilibrar fala, música e efeitos; ao corrigir pico, silêncio, LRA alto ou delta A/V.
- Antes da prévia e da exportação. Não serve para reparar ruído ou timbre.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: faixas, ids, tempos, volume, fades, velocidade e áudio de cada fonte.
2. Faixas reais: só existe `a1` de áudio; música e efeitos entram embutidos num clipe de `v1`/`v2` ou como clipes sequenciais em `a1` (sobreposição na mesma faixa é recusada). O áudio embutido no vídeo também precisa ser medido.
3. Meça clipe por clipe antes de mexer no volume: `analyze_timeline_clip(project_id, clip_id, kind="loudness")` devolve `medicoes` com `integrated_lufs`, `lra_lu` e `true_peak_dbfs` da janela exata do clipe. É só medida: não corta nem grava nada.
4. Dead air: `analyze_timeline_clip(project_id, clip_id, kind="silence", noise=-30, min_pause=0.5)` devolve `start`/`end`/`duration` em tempo de timeline, mais os `source_*` no arquivo. Trocas de cena: `kind="scenes", threshold=15` (1–100; menor acha mais), com score.
5. Mix completo: prévia (`preview=true`) + `check_render_job` → `loudness_lufs`, `lra_lu`, `true_peak_dbfs`, `black_ranges`, `av_start_delta` medidos no arquivo renderizado.
6. -14 LUFS para YouTube, não universal; -23 LUFS em broadcast. Confirme o destino.
7. Pico ≤ -1 dBTP; aviso acima de -0,1 dBFS; limitador fixo 0,95 (≈ -0,45 dBFS), não é alvo.
8. LRA 5–12 LU (>15 revisar); `audio_silence` < -60 LUFS; `av_start_delta` ≤ 0,15 s.

## 4. Procedimento
1. Meça cada clipe com `analyze_timeline_clip(project_id, clip_id, kind="loudness")` e registre `integrated_lufs`, `lra_lu`, `true_peak_dbfs`; sem medição não há diagnóstico, só chute.
2. Converta o desvio até a meta em dB e aplique como `set_timeline_clip(volume=...)`: passos de 1–2 dB = fator 0,89–1,12. Meça de novo o mesmo clipe depois de cada ajuste; um controle por vez.
3. Fala em `volume=1.0`; use 1,2–1,5 se baixa e 0,7–0,9 se quente; teto 2,0 (+6 dB).
4. Música sob fala 0,12–0,25 (≈ -18 a -12 dB); sozinha 0,35–0,6; efeitos 0,2–0,6, abaixo da fala.
5. Fades com `set_timeline_clip`: fala 0,1–0,25 s in e 0,15–0,4 s out; música 0,5–2,0 s. `speed` 0,1–8 preserva o pitch; fala 0,9–1,1.
6. Pausas: `analyze_timeline_clip(project_id, clip_id, kind="silence", noise=-30, min_pause=0.5)`; `apply_candidates=true` grava regiões no grupo `pausas` num único undo (duplicados são pulados, marcadores e regiões feitos à mão ficam intactos, mais de 400 candidatos é recusado). O humano revê na faixa da timeline e no painel "Análise" do inspector. Candidato não é corte: `split_timeline_clip`/`delete_timeline_clip` só com aval dele; para reanalisar, `clear_timeline_annotations(project_id, group="pausas")`. Cenas usam o mesmo caminho com `kind="scenes", apply_candidates=true` (grupo `cenas`); `loudness` não grava nada.
7. Prévia (`preview=true`), compare os números por clipe com os do render, valide e exporte com `preview=false`; o QC final vale mais que a prévia 360p.

## 5. Critérios e parâmetros
- Fala: 0,9–1,3 (1,0 é âncora; 2,0 é teto prático).
- Música sob fala: 0,12–0,25 (≈ -18 a -12 dB); sozinha: 0,35–0,6.
- Efeitos: 0,2–0,6, com pico abaixo da fala.
- Fades: fala 0,1–0,4 s; música 0,5–2,0 s.
- Loudness: -14 LUFS ±1 para YouTube; pico ≤ -1 dBTP, com margem de 0,3–0,5 dB na exportação.
- LRA: 5–12 LU; acima de 15 LU, revisar.
- Parâmetros da medição: `kind="loudness"` (sem limiar) devolve `integrated_lufs`, `lra_lu`, `true_peak_dbfs`; `kind="silence"` usa `noise` em dB (ex.: -30) e `min_pause` em s; `kind="scenes"` usa `threshold` 1–100 e devolve `time` (timeline), `source_time` (arquivo) e `score`.
- Pico confiável exige janela recortada no áudio decodificado (`atrim`/`asetpts` dentro do filtro, como a análise faz): seek de entrada (`-ss`) descarta ~21 ms de priming do AAC e já escondeu o pico real (0,1 dBFS lidos contra 3,9 medidos no material de teste).
Volume e fades são estáticos por clipe; o limitador não tem threshold ajustável e não há automação.

## 6. Erros comuns
- Normalizar de ouvido em vez de medir.
- Subir toda a fala em +6 dB: o ruído sobe e a mixagem achata.
- Deixar música em 0,5 sob diálogo; comece em 0,15.
- Fade de 1 s em frase curta: come palavras; use 0,15–0,25 s.
- Somar trilhas sem medir; a soma pode clipar.
- Chutar o LUFS do clipe antes de medir, ou aceitar o número do render como se fosse do clipe.
- Tratar candidato da análise como corte feito: `apply_candidates` só marca, não edita a timeline.

## 7. Checklist de qualidade
- [ ] Fala à frente da música.
- [ ] `kind="loudness"` medido em cada clipe antes e depois do ajuste de `volume`.
- [ ] Loudness na referência e pico ≤ -1 dBTP no QC final.
- [ ] Fades sem cortes de sílaba.
- [ ] Sincronia conferida no início, meio e fim.
- [ ] Marcadores e QC final registrados.

## 8. Validação objetiva
1. `analyze_timeline_clip` por clipe com `kind="loudness"`: dentro da referência do destino e com pico abaixo de -1 dBTP; `kind="silence"` com as pausas que sobraram conferidas por tempo, não por ouvido.
2. `validate_timeline` com `ok=true` e nenhum erro.
3. `check_render_job` com `status=done` e `qc.ok=true`; leia os avisos.
4. Loudness na referência, pico ≤ -1 dBTP, LRA 5–12 LU e `av_start_delta` ≤ 0,15 s.
5. Sem `audio_silence`, `audio_peak` nem `av_sync`; exporte e repita o QC, mantendo 0,3–0,5 dB de margem.
6. O agente não ouve: a medição substitui o chute, não o ouvido. Peça revisão humana de inteligibilidade, timbre e naturalidade dos fades.

## 9. Limitações atuais do ClipMind
- Medição existe: `analyze_timeline_clip(kind="loudness")` devolve LUFS integrado, LRA e true peak da janela do clipe; `kind="silence"` devolve intervalos de pausa; `kind="scenes"` devolve trocas de cena com score, em tempo de timeline e de arquivo. `apply_candidates=true` grava marcadores (`cenas`) ou regiões (`pausas`) num único undo e `clear_timeline_annotations` remove só esse grupo. O QC do render reporta `loudness_lufs`, `lra_lu`, `true_peak_dbfs` e `black_ranges` medidos.
- Medir não normaliza: nada no motor leva o áudio a -14 LUFS sozinho. Corrigir loudness é `volume` por clipe, re-medir e re-renderizar. `loudnorm` exigiria mudança de código.
- Não há EQ, compressão, de-esser, redução de ruído nem ducking por sidechain.
- O limitador é fixo em 0,95 (≈ -0,45 dBFS), sem threshold, release ou ceiling; não há automação de volume, keyframes, crossfade dedicado, waveform, curva de pico por instante, correlação, espectro ou stems.
- Só existe a faixa `a1` de áudio; não há ferramenta para criar `a2`/`a3`. Mute prático é `volume=0`; não há parâmetro dedicado de mute. FFmpeg externo não atualiza o projeto sem mudança de código.
- A análise não corta: quem decide o corte é o humano, e `trim_timeline_clip`/`split_timeline_clip`/`delete_timeline_clip` vêm depois da aprovação.

## 10. Ferramentas e skills relacionadas
- Medição e limpeza de candidatos: `analyze_timeline_clip` (`kind="loudness"`, `"silence"`, `"scenes"`), `clear_timeline_annotations`.
- Ajuste e validação: `inspect_edit_project`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Catálogo: `list_editor_skills`, `load_editor_skill`.
- Skills afins: `color-correction`, `color-grading`, `motion-graphics`, `subtitles-and-captions`.
