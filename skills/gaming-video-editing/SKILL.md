---
name: gaming-video-editing
title: Edição de Vídeos de Gaming
description: Highlights de gameplay por timecodes do usuário, velocidade constante em montagens, fades e música baixada por volume; sem beat detection.
triggers: gameplay, gaming, highlight, montagem, jogo, comentário, velocidade, kills
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_text, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Quando usar
- Highlights, montagem, let's play ou análise de gameplay com narração.
- Fonte gravada a 60 fps e muita ação em movimento rápido.
- Não use para aula de software (`tutorial-editing`) nem podcast falado (`podcast-editing`).

## 2. Objetivo
Transformar captura longa em vídeo de ritmo tenso: blocos de jogabilidade, momentos de kill/objetivo escolhidos pelo usuário, comentário inteligível e montagens aceleradas. Sem análise de conteúdo, a IA executa timestamps e ajusta ritmo por números.

## 3. Entradas necessárias
- Captura e gravação de voz com caminhos absolutos (separadas, quando possível).
- Lista de timestamps dos highlights; não há detecção de kill, cena ou beat.
- Música licenciada e estrutura (duração total, blocos).
- fps real da captura: 60 só se a fonte for 60.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.

## 5. Fluxo passo a passo
1. `inspect_edit_project`; confirme faixas, ids e duração da captura.
2. Projeto 1920x1080@60 quando a fonte for 60; fonte 30 → projeto 30 (não há interpolação).
3. Converta os timestamps do usuário em `in_point`/`out_point` e marque cada highlight com `add_timeline_marker` antes de cortar.
4. Cold open 3–5 s com o melhor momento; blocos de 60–120 s com plano de 2,5–5 s; não corte no meio da ação.
5. Montagem: `split_timeline_clip` + `set_timeline_clip(speed=2 a 4)`; velocidade é constante, sem rampa; "aceleração" se simula com trechos de velocidades diferentes.
6. Slow-mo de impacto só com fonte 60 (`speed=0,25–0,5`); em fonte 30 fica aos saltos — avise.
7. Áudio: comentário com `volume` 1,0–1,4; jogo em `v1` reduzido a 0,35–0,6. Música sob a voz só quando a voz embute no vídeo (`a1` livre); se voz e música são dois `.mp3`, `a1` não aceita sobreposição — coloque a música nas pausas ou peça pre-mix fora. Ducking manual = baixar volume por clipe.
8. Fades de 0,15–0,3 s nas emendas de velocidade para disfarçar o salto; fade é a única transição.
9. `validate_timeline`, prévia, ajuste loudness, exporte CRF 18–20 e confira o QC.

## 6. Regras obrigatórias
- Nunca alegar ter "visto" a jogada: os momentos vêm do usuário.
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
- Esperar cortes no ritmo da música: sem beat detection, alinhe por timestamps.
- Rampa de velocidade "de verdade": não existe; só constante.
- Música cobrindo a voz por esquecer o volume por clipe.
- Ripple em uma faixa sem corrigir a outra, quebrando a sincronia.

## 9. Limitações do sistema atual
Sem detecção de highlights, kills, cenas ou beats; sem transcrição; sem análise de imagem ou áudio. Não há curvas de velocidade, keyframes, ducking automático, normalização de loudness, rastreamento, multicam, LUTs nem overlays animados. Transição é só fade. Compense: velocidade constante + fades, volume por clipe como ducking, marcadores como lista de momentos — e avise que são escolhas manuais.

## 10. Exemplo de uso
Usuário: "Corta os highlights em 00:14:20, 00:31:05 e 00:58:40 e faz montagem 3× entre o 2º e o 3º."
1. `add_timeline_clip(track="v1", source="captura.mp4", in_point=860, out_point=872)` para cada momento.
2. Travessia: `add_timeline_clip(track="v1", source="captura.mp4", in_point=1865, out_point=1900, speed=3, volume=0)`.
3. `set_timeline_clip(clip_id=..., fade_in=0.2, fade_out=0.2)` nas emendas da montagem.
4. Voz em `a1` (volume 1,2); música em clipes de `a1` só entre as falas (volume 0,3).
5. `validate_timeline` → prévia → exporte 1080p60 CRF 18, declarando que a seleção seguiu timestamps do usuário e que a "rampa" é velocidade constante.
