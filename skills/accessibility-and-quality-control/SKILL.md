---
name: accessibility-and-quality-control
title: Acessibilidade e controle de qualidade
description: Legendas queimadas legíveis, áreas seguras, inteligibilidade e QC técnico com triagem de severidade.
triggers: acessibilidade, legendas para surdos, contraste, área segura, controle de qualidade, QC, loudness, legibilidade, triagem
tools: configure_edit_project, inspect_edit_project, add_timeline_text, add_timeline_subtitles, trim_timeline_clip, set_timeline_clip, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip
---

## 1. Objetivo
Garantir um vídeo compreensível para pessoas surdas e tecnicamente íntegro. Acessibilidade aqui é legenda queimada legível, contraste, área segura e áudio inteligível; QC técnico é separado da narrativa.

## 2. Quando usar
Use quando houver fala e o destino exigir legendas, em conteúdo sem som e antes de entregar. Não use para prometer transcrição, legenda automática ou faixa desativável.

## 3. Diagnóstico antes de editar
- `inspect_edit_project`: resolução, fps, duração, faixas e clipes.
- Confirme o arquivo `.srt`, `.vtt` ou `.ass` fornecido. Sem arquivo, não invente texto nem prometa transcrição.
- Verifique áudio na fonte ou na a1 e defina a área segura (16:9 ou 9:16).
- Meça o clipe antes de concluir que o áudio está ruim: `analyze_timeline_clip(project_id, clip_id, kind="loudness")` devolve `integrated_lufs`, `lra_lu` e `true_peak_dbfs`; `kind="silence"` com `noise=-30` e `min_pause=0.5` mede as pausas longas que a legenda também precisa cobrir.
- Rode `validate_timeline` para separar erro de aviso.

## 4. Procedimento
1. Ajuste a resolução final antes de posicionar legendas.
2. Verifique o arquivo em UTF-8 e com tempos válidos.
3. Adicione com `add_timeline_subtitles` (`start`, `font_size`, `position`, `margin_v`).
4. Ajuste com `set_timeline_clip` (`subtitle_font_size`, `subtitle_margin_v`, `subtitle_color`).
5. Títulos: `add_timeline_text` com `background=true`, contraste alto e até duas linhas.
6. Dessincronia: ajuste o `start` ou recrie o clipe; não estique o texto.
7. Áudio: meça por clipe (`analyze_timeline_clip(kind="loudness")`), ajuste `volume` (0–4) e meça de novo. Sem EQ, compressão ou normalização no motor. Se a fala continuar ruim, trate fora e reimporte.
8. Prévia 360p: revise cortes rápidos e alto contraste; não há detector de flash.
9. Triagem: corrija `error`, decida `warning` com o usuário e registre `info`.

## 5. Critérios e parâmetros
- Legenda: 28–40 px em 1080p e 40–56 px em 1080x1920; até 2 linhas e ~42 caracteres por linha.
- Margem vertical de 5% da altura, longe de botões e UI da plataforma.
- Contraste alto; branco ou amarelo com contorno preto; evite texto claro em cena clara.
- Áudio: -14 LUFS, true peak até -1 dBFS e LRA baixo em fala. O QC avisa acima de -0,1 dBFS e abaixo de -60 LUFS. Os mesmos números saem por clipe em `analyze_timeline_clip(kind="loudness")`, antes do render.
- Evite mais de três flashes/s; revise manualmente.
- `error` bloqueia; `warning` é risco; `info` é contexto.

## 6. Erros comuns
- Prometer transcrição ou legenda automática: não existe.
- Tratar legenda queimada como opcional; ela faz parte da imagem.
- Fonte pequena porque a prévia 360p parece legível.
- Ignorar área segura em Shorts e texto sob a interface.
- Usar `start` errado e acumular atraso.
- Confundir loudness alto com fala inteligível.
- Avaliar narrativa pelo QC: ele não entende conteúdo.

## 7. Checklist de qualidade
- [ ] Legenda existe, abre, tem tempos coerentes e aparece do início ao fim da fala.
- [ ] Tamanho, cor, margem e posição conferidos no quadro final.
- [ ] Nenhum texto essencial fora da área segura.
- [ ] Áudio presente, sem clipping e com loudness medido (`analyze_timeline_clip` no clipe, QC no render).
- [ ] Nenhum erro de validação; avisos explicados.
- [ ] Prévia assistida; narrativa avaliada por humano.

## 8. Validação objetiva
`validate_timeline` sem `error`; job com `status: done` e `qc.ok: true`. Leia `duration`, `has_audio`, `loudness_lufs`, `lra_lu`, `true_peak_dbfs`, `black_ranges` e `av_start_delta` (aviso acima de 0,15 s): são medidas reais do arquivo (ebur128 e blackdetect), não estimativas — os mesmos medidores da análise por clipe. Se `loudness_qc_skipped` ou `black_qc_skipped` aparecer, não houve medição, e arquivo não verificado não é arquivo aprovado. O QC não faz OCR: presença e legibilidade da legenda são conferidas visualmente. `black_frames` é aviso, pode ser intencional.

## 9. Limitações atuais do ClipMind
Existe medição: `analyze_timeline_clip` roda FFmpeg num clipe e devolve LUFS integrado, LRA e true peak (`kind="loudness"`), intervalos de pausa (`kind="silence"`, com `noise` e `min_pause`) e trocas de cena com score (`kind="scenes"`). O QC do render usa os mesmos leitores e reporta `loudness_lufs`, `lra_lu`, `true_peak_dbfs` e `black_ranges`. Medir não é avaliar acessibilidade: inteligibilidade, contraste e legibilidade continuam conferidos por humano.
Não existe: transcrição, legenda automática, faixa CC alternável, identificação de falante, audiodescrição, waveform, curva de pico por instante, detector de flash, EQ, compressor, normalização para LUFS alvo, automação de volume, keyframes, LUT, balanço de branco e scopes. Legenda é só queimada na imagem e só há a faixa `a1`; a prévia é um render 360p. Alternativas: gerar `.srt` externo, ajustar `volume` por clipe com medição antes e depois, tratar áudio fora e reimportar, revisar flashes manualmente. Para automatizar faltariam ASR, modelo de legendas, stream separado, análise de flash e cadeia de filtros de áudio.

## 10. Ferramentas e skills relacionadas
Ferramentas: `configure_edit_project`, `inspect_edit_project`, `add_timeline_text`, `add_timeline_subtitles`, `set_timeline_clip`, `analyze_timeline_clip` (só leitura: este procedimento não grava candidatos, então não usa `clear_timeline_annotations`), `validate_timeline`, `render_timeline`, `check_render_job`. Skills: `export-and-delivery`, `render-diagnostics`, `timeline-debugging` e `multicam-editing`.
