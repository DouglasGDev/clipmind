---
name: documentary-editing
title: Edição de Documentário
description: Narrativa documental com entrevistas, marcadores de capítulo e equilíbrio de volume por clipe; sem transcrição, o usuário fornece timecodes.
triggers: documentário, entrevista, narrativa, cartela, capítulo, b-roll, continuidade, arquivo
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Quando usar
- Documentário, reportagem, perfil ou institucional montado sobre entrevistas.
- B-roll, arquivo e música cobrem cortes e sustentam o arco.
- Não use para podcast sem imagem (`podcast-editing`) nem tutorial (`tutorial-editing`).

## 2. Objetivo
Estruturar o material falado em arco (contexto, conflito, virada, resolução) com cortes limpos, cartelas e capítulos marcados. O ClipMind mede o clipe (cenas, pausas, loudness) mas não entende o que é dito: a ordem do arco vem do usuário; a IA propõe candidatos, declara suposições e corta só depois do aval humano.

## 3. Entradas necessárias
- Caminhos absolutos de entrevistas, b-roll, arquivo e música, confirmados pelo usuário.
- Timecodes dos sound bites e das fronteiras de capítulo, ou descrição explícita de cada momento. Não existe transcrição automática: o texto da fala vem do usuário. A borda do bite e a virada de capítulo podem ser medidas em `analyze_timeline_clip` (`kind="silence"` para pausas, `kind="scenes"` para trocas de plano) e revisadas como candidatos.
- Nome/função/local para cartelas, definição do arco e direitos do arquivo.
- Resolução e fps do destino (1920x1080@24 ou @30).

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `add_timeline_subtitles`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`, `analyze_timeline_clip`, `clear_timeline_annotations`.

## 5. Fluxo passo a passo
1. `inspect_edit_project` antes de tudo; confirme ids, faixas e arquivos citados.
2. Projeto 1920x1080 com fps igual ao da fonte; não misture 24 e 30.
3. Peça timecodes das falas (8–20 s); sem eles, meça o clipe com `analyze_timeline_clip(kind="silence", noise=-30, min_pause=0.4)` e proponha a borda do bite pela pausa, declarando o que veio da medição e o que veio da descrição do usuário.
4. Monte as entrevistas em `v1` com `add_timeline_clip`; `in_point`/`out_point` são segundos do arquivo.
5. Marque capítulos com `add_timeline_marker`; as viradas medidas (`kind="scenes"`, `apply_candidates=true`) entram como marcadores do grupo `cenas` para o humano escolher. Marcadores não saem no MP4, copie os tempos na resposta.
6. Cubra jump cuts com b-roll em `v2` (2–4 s); não esconda o rosto nos pontos-chave.
7. Cartelas em `t1`: nome/função e local/data, 4–6 s, 40–56 px, `position="inferior-esquerda"`.
8. Áudio: antes de mexer, meça `analyze_timeline_clip(kind="loudness")` no clipe (LUFS integrado, LRA, true peak); fala `volume=1,0`; música 0,15–0,25 sob fala e 0,4–0,6 em pausa, ajustada por clipe com `set_timeline_clip`; não há ducking nem normalização automática.
9. `validate_timeline` sem erros, prévia 360p, leia o loudness do QC, ajuste volumes e exporte `preview=false`.

## 6. Regras obrigatórias
- Nunca invente timecodes; sem entrada do usuário, meça com `analyze_timeline_clip` e mostre os tempos obtidos, ou pergunte e declare o palpite.
- Fades são a única transição; transição fade ≤ metade do clipe.
- Não sobreponha clipes na mesma faixa; b-roll em `v2`, música apenas em `a1`.
- Handles de 0,3–0,5 s em todo corte de fala; exclua só com `confirm=true` após aval explícito.
- Diga na resposta o que é decisão sua e o que é instrução recebida.

## 7. Critérios de qualidade
- Sound bites completos, 8–20 s, sem cortar ideia no meio.
- Cartelas legíveis com créditos; legenda queimada para fala estrangeira.
- Loudness medido no QC em torno de -14 LUFS (±2) e true peak ≤ -1 dBTP.
- Validação `ok=true`, prévia revisada e QC final aprovado na exportação.

## 8. Erros comuns
- Agir como se houvesse assistido ao material: a medição devolve tempos e níveis, não o sentido da fala.
- Música cobrindo a fala por esquecer o volume fixo por clipe.
- B-roll na entrevista inteira, escondendo rostos e olhares.
- Tratar marcador como capítulo exportado; o MP4 não recebe capítulos.
- Tratar candidato de cena ou pausa como corte já decidido: cortar é do humano.
- Presumir LUT, multicam, auto-reframe, sincronia automática ou normalização de loudness.

## 9. Limitações do sistema atual
`analyze_timeline_clip` mede um clipe por vez com FFmpeg: `kind="scenes"` (`scdet`) dá as trocas de plano com score e os tempos da timeline e do arquivo, `kind="silence"` (`silencedetect`) dá as pausas com início e fim, `kind="loudness"` (`ebur128`) dá LUFS integrado, LRA em LU e true peak em dBFS do recorte. `apply_candidates=true` grava cenas como marcadores (`cenas`) e pausas como regiões (`pausas`) num único passo de undo, preservando o que foi criado à mão e pulando duplicados; `clear_timeline_annotations(group)` remove o grupo medido. A análise não corta nada e `loudness` não escreve nada — medir LUFS não normaliza. Não há transcrição (Whisper), texto ou timecode de fala, detecção de falante, beat, waveform, curva de nível por momento, keyframes/curvas, rastreamento de rosto, auto-reframe, sync multicam, LUTs, EQ/compressor/denoiser/ducking (só `afade` e `volume` 0–4 por clipe, limitador fixo). Transição é só fade; velocidade constante 0,1–8, sem rampas; cor é eq (brilho/contraste/saturação/gamma). Prévia é render 360p, não tempo real. Legendas `.srt/.vtt/.ass` queimadas via libass. O que a medição não alcança, faça o equivalente manual (marcadores + offsets + volume por clipe) e declare isso na resposta.

## 10. Exemplo de uso
Usuário: "Entrevista `entrevista1.mp4`: use a fala de 00:12:05 a 00:12:38 e o capítulo 2 começa em 00:15:00."
1. `add_timeline_clip(track="v1", source="entrevista1.mp4", in_point=725, out_point=758)`.
2. `add_timeline_marker(time=900, label="capítulo 2")`.
3. `add_timeline_text(text="Maria — bióloga", start=725, duration=5, font_size=44, position="inferior-esquerda")`.
4. `add_timeline_clip(track="a1", source="trilha.mp3", volume=0.2)`.
5. `validate_timeline` → `render_timeline(preview=true)` → `check_render_job` → exporte. Informe que marcadores não viram capítulos no MP4 e que a seleção dos trechos veio do usuário.
