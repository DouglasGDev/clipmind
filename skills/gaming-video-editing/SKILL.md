---
name: gaming-video-editing
title: Edição de Vídeos de Gaming
description: Highlights de gameplay por timecodes do usuário, velocidade constante em montagens, fades e música baixada por volume; sem beat detection.
triggers: gameplay, gaming, highlight, montagem, jogo, comentário, velocidade, kills
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_text, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Quando usar
- Highlights, montagem, let's play ou análise de gameplay com narração.
- Fonte gravada a 60 fps e muita ação em movimento rápido.
- Não use para aula de software (`tutorial-editing`) nem podcast falado (`podcast-editing`).

## 2. Objetivo
Transformar captura longa em vídeo de ritmo tenso: blocos de jogabilidade, momentos de kill/objetivo escolhidos pelo usuário, comentário inteligível e montagens aceleradas. `analyze_timeline_clip` mede troca de cena, pausa e nível de um clipe e entrega números; não reconhece jogada, kill, objetivo nem beat — a IA executa os timestamps do usuário e ajusta ritmo por medidas, não por suposição.

## 3. Entradas necessárias
- Captura e gravação de voz com caminhos absolutos (separadas, quando possível).
- Lista de timestamps dos highlights: kill, objetivo e beat não são detectáveis; troca de cena, pausa e nível são medidos por clipe.
- Música licenciada e estrutura (duração total, blocos).
- fps real da captura: 60 só se a fonte for 60.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`, `analyze_timeline_clip`, `clear_timeline_annotations`.

## 5. Fluxo passo a passo
1. `inspect_edit_project`; confirme faixas, ids e duração da captura.
2. Projeto 1920x1080@60 quando a fonte for 60; fonte 30 → projeto 30 (não há interpolação).
3. Meça antes de cortar, um clipe por vez: `analyze_timeline_clip(kind="scenes", threshold=15)` devolve cada troca de cena com score e com o tempo de arquivo e de timeline (útil em cobertura e montagem); `analyze_timeline_clip(kind="silence", noise=-35, min_pause=0.4)` acha o dead air; `analyze_timeline_clip(kind="loudness")` dá LUFS integrado, LRA e true peak daquela janela. Os números vêm da medição, nunca de chute.
4. Converta os timestamps do usuário em `in_point`/`out_point` e marque cada highlight com `add_timeline_marker` antes de cortar. Para a sugestão medida aparecer na régua e no inspetor, `apply_candidates=true` grava marcadores `cenas` ou regiões `pausas` num único passo de undo; `clear_timeline_annotations(group="cenas")` remove só o que a análise escreveu. Nada disso corta: `trim_timeline_clip`/`split_timeline_clip`/`delete_timeline_clip` vêm depois, com aval.
5. Cold open 3–5 s com o melhor momento; blocos de 60–120 s com plano de 2,5–5 s; não corte no meio da ação.
6. Montagem: use as trocas de `kind="scenes"` como grade de corte; `split_timeline_clip` + `set_timeline_clip(speed=2 a 4)`; velocidade é constante, sem rampa; "aceleração" se simula com trechos de velocidades diferentes.
7. Slow-mo de impacto só com fonte 60 (`speed=0,25–0,5`); em fonte 30 fica aos saltos — avise.
8. Áudio: comente com `volume` 1,0–1,4 sobre o jogo em `v1` a 0,35–0,6, partindo do LUFS e do pico medidos. Música sob a voz só quando a voz embute no vídeo (`a1` livre); se voz e música são dois `.mp3`, `a1` não aceita sobreposição — coloque a música nas pausas medidas ou peça pre-mix fora. Ducking manual = baixar volume por clipe.
9. Fades de 0,15–0,3 s nas emendas de velocidade para disfarçar o salto; fade é a única transição.
10. `validate_timeline`, prévia, ajuste o `volume` pelo loudness medido, exporte CRF 18–20 e confira o QC.

## 6. Regras obrigatórias
- Nunca alegar ter "visto" a jogada: a medição aponta troca de cena, pausa e nível, não o feito; o momento vem do usuário.
- Alterar `speed` muda a duração e pode colidir na faixa; reinspecione depois.
- Áudio acelerado/esticado soa mal: zere ou baixe o volume nos clipes com speed ≠ 1.
- Voz e jogo no mesmo arquivo não se separam; peça faixas separadas.
- Exclusões exigem `delete_timeline_clip(confirm=true)` após aval.

## 7. Critérios de qualidade
- 60 fps preservados quando a fonte permite; CRF 18–20.
- Cada kill/objetivo com 1–2 s de contexto antes e depois.
- Comentário inteligível: voz 8–12 dB acima do jogo; loudness -14 ±2 LUFS, pico ≤ -1 dBTP.
- Sem over-cutting (plano ≥ 2 s) e sem preto involuntário de loading.

## 8. Erros comuns
- Projeto 60 com fonte 30: quadros duplicados.
- Esperar cortes no ritmo da música: não há beat detection; alinhe por timestamps do usuário ou pelas trocas de cena medidas.
- Rampa de velocidade "de verdade": não existe; só constante.
- Música cobrindo a voz por esquecer o volume por clipe.
- Ripple em uma faixa sem corrigir a outra, quebrando a sincronia.

## 9. Limitações do sistema atual
Há medição por clipe, não interpretação: `analyze_timeline_clip` roda FFmpeg num clipe da timeline e devolve candidatos — `kind="scenes"` (scdet) traz as trocas de cena com score de 1 a 100 e o tempo de arquivo e de timeline; `kind="silence"` (silencedetect) traz início e fim de cada pausa conforme `noise` em dB e `min_pause` em s; `kind="loudness"` (ebur128) traz três números daquela janela (LUFS integrado, LRA em LU, true peak em dBFS) e não escreve nada; `kind="peaks"` (astats) traz a curva de pico por instante e os trechos acima da mediana. Não existe detecção de kill, highlight, objetivo nem beat; há curva de áudio por instante, mas não waveform desenhada na timeline; não há transcrição. Com `apply_candidates=true` as cenas e os picos viram marcadores (`cenas`, `picos`) e as pausas, regiões (`pausas`), num passo de undo: o que foi marcado à mão fica, duplicado é ignorado e acima de 400 candidatos a gravação falha; `clear_timeline_annotations` limpa só esse grupo. A medição não corta. Sem curvas de velocidade, keyframes, ducking automático, normalização de loudness, rastreamento, multicam, LUTs nem overlays animados. Transição é só fade. Compense: velocidade constante + fades, volume por clipe, marcadores como lista de momentos — e avise que a seleção é sua.

## 10. Exemplo de uso
Usuário: "Corta os highlights em 00:14:20, 00:31:05 e 00:58:40 e faz montagem 3× entre o 2º e o 3º."
1. `add_timeline_clip(track="v1", source="captura.mp4", in_point=860, out_point=872)` para cada momento.
2. Travessia sem chute: `analyze_timeline_clip(project_id=..., clip_id=..., kind="scenes", threshold=15, apply_candidates=true)` deixa as trocas de cena como marcadores `cenas` na régua, para o humano aprovar; o corte vem depois.
3. Travessia: `add_timeline_clip(track="v1", source="captura.mp4", in_point=1865, out_point=1900, speed=3, volume=0)`.
4. `set_timeline_clip(clip_id=..., fade_in=0.2, fade_out=0.2)` nas emendas da montagem.
5. Voz em `a1` (volume 1,2) checando o LUFS e o pico com `kind="loudness"`; música em clipes de `a1` só entre as falas (volume 0,3).
6. `validate_timeline` → prévia → exporte 1080p60 CRF 18, declarando que a seleção dos momentos seguiu timestamps do usuário, que a cena medida só apontou fronteiras e que a "rampa" é velocidade constante.
