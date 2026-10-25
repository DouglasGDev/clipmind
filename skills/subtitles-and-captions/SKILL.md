---
name: subtitles-and-captions
title: Legendas e Captions
description: Importa SRT/VTT/ASS como legenda queimada, corrige offset por start, estilo com tamanho/cor/margem e revisão por prévia; não transcreve.
triggers: legenda, legendas, srt, vtt, ass, legenda queimada, closed caption, acessibilidade, sincronia
tools: inspect_edit_project, add_timeline_subtitles, add_timeline_text, move_timeline_clip, trim_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Quando usar
- Cliente entrega `.srt`, `.vtt` ou `.ass` pronto (ou gerado fora) para queimar no vídeo.
- Corrigir offset, tamanho, posição ou margem de legenda já na timeline.
- Acessibilidade, versão sem som e redes sociais.
- Não use para gerar texto de fala: não há transcrição.

## 2. Objetivo
Queimar legendas legíveis e sincronizadas tratando o arquivo como verdade: o ClipMind só insere o `.srt/.vtt/.ass` via libass. O trabalho do editor é offset, estilo, área segura e revisão.

## 3. Entradas necessárias
- Arquivo de legenda com caminho absoluto, UTF-8, e a primeira/última cue conhecidas.
- Instante da timeline em que a primeira cue deve aparecer (para calcular `start`).
- Formato do vídeo (16:9 ou 9:16) e posição de títulos/UI que não podem ser cobertos.
- Se não houver arquivo: transcreva fora (Whisper/Aegisub) e revise; a IA pode redigir o `.srt` como texto, nunca "de ouvido".

## 4. Ferramentas disponíveis
`inspect_edit_project`, `add_timeline_subtitles`, `add_timeline_text`, `move_timeline_clip`, `trim_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.

## 5. Fluxo passo a passo
1. `inspect_edit_project`: confira `s1`, duração total e títulos em `t1`.
2. Prepare/edite o `.srt` fora (cues, tempos, ≤ 2 linhas por cue) e confira contagem e acentos.
3. Calcule `start = tempo_alvo_na_timeline - início_da_primeira_cue`; o `start` soma às cues do arquivo.
4. `add_timeline_subtitles(subtitle_path=..., start=..., font_size=..., position=..., margin_v=...)`; cor não é parâmetro de entrada.
5. Estilo fino com `set_timeline_clip(subtitle_font_size=, subtitle_margin_v=, subtitle_color=, subtitle_position=)`.
6. Descalibrou? `move_timeline_clip` pela diferença exata; todas as cues deslocam junto.
7. Prévia 360p: confira início, meio, fim, cortes e colisão com `t1`; ajuste tamanho/margem.
8. `validate_timeline`, registre offset/estilo em `add_timeline_marker` e exporte; qualquer correção depois exige reexportar.

## 6. Regras obrigatórias
- Nunca alegar sincronia sem conferir cue a cue na prévia; o QC não mede legenda.
- 16:9: fonte 22–28, `margin_v` 36–56; 9:16: fonte 24–32, `margin_v` 56–80 e folga dos 15–20% inferiores (UI).
- Máximo 2 linhas; ~42 caracteres por linha em 16:9, ~30 em 9:16; leitura ≤ 18 caracteres/s (ideal 12–15 CPS).
- Cue fora da janela do clipe é cortada: confirme a última cue contra a duração.
- Ao mudar `speed` ou cortar vídeo, a legenda não acompanha: retimar o arquivo fora e refazer o offset.

## 7. Critérios de qualidade
- Primeira cue exatamente no tempo combinado; nenhuma sobreposição de cues.
- Branco com contorno (padrão do libass); cor só via `subtitle_color`.
- Sem colisão com títulos, lower thirds ou botões da plataforma.
- Prévia revisada em 360p e export com `qc.ok=true`; UTF-8 sem acentos corrompidos.

## 8. Erros comuns
- Somar o offset duas vezes quando o SRT já nasce em tempo de timeline (`start=0`).
- Usar `start` achando que ele reescreve os tempos internos; ele apenas desloca o bloco.
- Legenda pequena no celular, margem baixa demais ou texto sob a UI do Shorts.
- Esperar legenda automática, karaokê, destaque por palavra ou cores por falante.
- Deixar legenda de vídeo que foi acelerado sem retimar — desincroniza todo o resto.

## 9. Limitações do sistema atual
Sem Whisper/transcrição, tradução, editor de cues interno, destaque palavra a palavra, faixa soft, sidecar, detecção de falante e QC de legenda. Só queima `.srt/.vtt/.ass` via libass, com estilo limitado a `font_size`, `position` (inferior/centro/topo), `color` e `margin_v` pelo `set_timeline_clip`; ASS segue o `force_style` básico fixo (fonte padrão, contorno/sombra não configuráveis). Sem keyframes nem prévia em tempo real. Diga ao usuário que texto e tempos vêm de arquivo externo revisado por humano.

## 10. Exemplo de uso
Usuário: "Legenda `video.srt` (começa em 00:00:02) para aparecer aos 10 s do vídeo, em 9:16."
1. `start = 10 - 2 = 8` → `add_timeline_subtitles(subtitle_path="video.srt", start=8, font_size=28, position="inferior", margin_v=64)`.
2. `set_timeline_clip(clip_id=..., subtitle_color="white", subtitle_margin_v=64)`.
3. Prévia: 1ª cue bate aos 10 s; 30% do meio e fim conferidos; sem cobrir UI.
4. Fica 0,5 s adiantada: `move_timeline_clip(clip_id=..., start=7.5)`.
5. `validate_timeline` → exporte. Informe: texto veio do arquivo fornecido, sem transcrição automática, e retiming futuro exige editar o SRT fora.
