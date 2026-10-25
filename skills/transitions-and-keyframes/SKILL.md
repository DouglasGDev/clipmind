---
name: transitions-and-keyframes
title: Transições e Keyframes
description: Fade real do ClipMind, duração segura e alternativas honestas para a animação por keyframes inexistente.
triggers: transição, fade, crossfade, keyframe, animação, opacity, corte seco, transição suave, movimento, curvas
tools: inspect_edit_project, add_timeline_clip, move_timeline_clip, trim_timeline_clip, split_timeline_clip, set_timeline_clip, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Objetivo
Usar o único fade disponível (alpha) com duração segura, preferir corte seco quando melhor e reconhecer que keyframes não existem. Não prometer animação contínua nem crossfade real.

## 2. Quando usar
- Para abrir ou fechar o vídeo.
- Para suavizar elipses de tempo e mudanças de tom.
- Para revelar B-roll sobreposto em v2.
- Quando pedirem transição, animação, zoom ou keyframes.

## 3. Diagnóstico antes de editar
1. Chame `inspect_edit_project` e anote ids, duração e fades.
2. Meça onde o plano muda em vez de chutar: `analyze_timeline_clip(clip_id, kind="scenes", threshold=15)` devolve as trocas de cena com score e os tempos da timeline e do arquivo; `kind="silence"` devolve as pausas onde o fade respira. Revise e grave como candidatos (`apply_candidates=true`) para o humano aprovar antes de editar.
3. Classifique o efeito: fade para preto (v1), revelação de sobreposição (v2), corte seco ou falso dissolve.
4. Verifique handles e vizinhos; fade não cria material novo e a análise não aplica transição.
5. Rode `validate_timeline` e veja avisos de transição > metade do clipe.
6. Se pedirem keyframe, explique a limitação e proponha a aproximação por segmentos antes de editar.

## 4. Procedimento
1. Carregue esta skill e inspecione; prefira corte seco em ação contínua, diálogo e mesma cena. Use fade em abertura, encerramento e salto de plano — nos pontos que `analyze_timeline_clip(kind="scenes")` mediu, não em tempo redondo.
2. Em vídeo, aplique `set_timeline_clip(transition_type="fade", transition_duration=0.5)`: cria entrada e saída no mesmo clipe, limitadas à metade. Para um lado só, use `fade_in` ou `fade_out`.
3. Durações: 0,3–0,6 s em sobreposição; 0,5–1,0 s em abertura/fechamento; nunca acima da metade.
4. Fade entre dois clipes na v1 mergulha no preto. Use em elipse, não em ação contínua.
5. Falso dissolve: B em v2 sobre A em v1, `fade_in` em B e `volume=0` para não duplicar áudio; não há xfade nem crossfade de áudio.
6. Aproximação de keyframe: divida em 3–6 segmentos e altere `transform_scale`, `transform_opacity` ou cor (1,00, 1,02, 1,04...). Há degraus; opacidade com fades curtos; zoom em passos de 1–3% e corte no movimento. Sem easing.
7. Valide, renderize prévia, revise e exporte.

## 5. Critérios e parâmetros
- Transição ≤ metade da duração do clipe; acima disso a ferramenta rejeita.
- Soma `fade_in + fade_out` ≤ duração do clipe.
- Títulos aceitam fades limitados à metade; legendas queimadas não têm fade.
- `transform_scale` 0,05–8; `opacity` 0–1; cor: brightness -1–1, contrast/saturation 0–4, gamma 0,1–10.
- Pseudo-keyframe: 3–6 segmentos de 0,5–2 s, saltos pequenos e revisão humana.
- Corte seco é o padrão; fade é exceção justificada.

## 6. Erros comuns
- Prometer xfade, wipe ou dip-to-color: só existe alpha fade.
- Usar `transition_type="fade"` esperando um lado; ele aplica entrada e saída.
- Deixar os dois clipes da v1 sumirem e criar preto acidental.
- Deixar o áudio do v2 audível, duplicando som.
- Vender segmentos como keyframe suave; há degraus visíveis.
- Usar fade para esconder corte mal feito em vez de corrigir o ponto.
- Tratar candidato de cena (grupo `cenas`) como transição aplicada: ele só marca o ponto.

## 7. Checklist de qualidade
- [ ] O efeito é fade ou corte seco, sem promessas de xfade.
- [ ] Duração dentro da metade do clipe.
- [ ] Fades somados cabem na duração.
- [ ] Áudio do overlay controlado.
- [ ] Aproximação aprovada e prévia/QC conferidos.

## 8. Validação objetiva
- `validate_timeline` sem erros e sem aviso de transição > metade.
- Conferir no inspect os valores de `transition`, `fade_in` e `fade_out`.
- `check_render_job` com `qc.ok=true`; trechos pretos ≥0,5 s só se forem fades intencionais.
- Delta A/V ≤0,15 s; true peak ≤ -0,1 dBFS.
- Revisar o export em resolução cheia; a prévia 360p esconde degraus.

## 9. Limitações atuais do ClipMind
Transição é só fade alpha por clipe: não há xfade, wipe, slide, dip-to-color, transição sonora automática nem curvas. Keyframes, easing e animação contínua não existem; são evolução futura, não recurso atual. Rastreamento e auto-reframe também não. `analyze_timeline_clip` mede um clipe por vez e serve para achar onde transicionar: `kind="scenes"` (`scdet`) traz as trocas de cena com score e os tempos da timeline e do arquivo, `kind="silence"` (`silencedetect`) traz as pausas, `kind="loudness"` (`ebur128`) traz LUFS integrado, LRA e true peak do recorte e `kind="peaks"` (`astats`) traz a curva de pico por instante com os trechos acima da mediana. `apply_candidates=true` grava cenas e picos como marcadores (`cenas`, `picos`) e pausas como regiões (`pausas`) num único undo, revisáveis no inspector "Análise" e removíveis com `clear_timeline_annotations`; a análise não corta nem aplica fade. Não há transcrição, waveform, LUT, curvas de cor, balanço de branco, escopos, EQ, compressor, de-esser, ducking nem normalização (só `afade` e `volume` 0–4 por clipe, limitador fixo); cor é brilho/contraste/saturação/gamma e a velocidade é constante. A prévia é um render 360p, não tempo real. Para animação suave, use editor externo ou aprove a aproximação por segmentos.

## 10. Ferramentas e skills relacionadas
- Transição: `set_timeline_clip`, `inspect_edit_project`.
- Sobreposição e segmentos: `add_timeline_clip`, `move_timeline_clip`, `trim_timeline_clip`, `split_timeline_clip`.
- Entrega: `validate_timeline`, `render_timeline`, `check_render_job`.
- Medição: `analyze_timeline_clip` (cenas, pausas, loudness), `clear_timeline_annotations`.
- Skills: `b-roll-planning`, `professional-cutting`, `video-editor-core`.
