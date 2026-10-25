---
name: multicam-editing
title: Edição multicâmera manual
description: Alinhe e alterne ângulos de câmera manualmente na timeline do ClipMind, sem sincronização automática.
triggers: multicâmera, multicam, troca de ângulo, sincronizar câmeras, duas câmeras, podcast multicam, corte entre câmeras, ângulo de câmera
tools: create_edit_project, inspect_edit_project, add_timeline_clip, trim_timeline_clip, split_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Objetivo
Montar uma edição multicâmera com ângulos alinhados e cortes limpos usando apenas os recursos do ClipMind. O resultado deve ter base contínua, trocas de ângulo intencionais e áudio sem duplicação.

## 2. Quando usar
Use em podcast, entrevista, show ou aula com duas ou mais câmeras do mesmo evento. Não use esperando sincronização automática, detecção de claque ou troca automática de ângulo: nada disso existe.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: resolução, fps, duração e ids.
2. Adicione cada ângulo e confira duração e áudio no inspect.
3. Escolha o ângulo base com o áudio principal.
4. Crie o projeto com a resolução e o fps do destino.
5. Marque com `add_timeline_marker` a referência (palma, batida, fala) em cada ângulo; é a única referência de sincronia.

## 4. Procedimento
1. Adicione o ângulo base na v1 em `start=0`, com o trecho em `in_point`/`out_point`.
2. Confira a duração e marque a sincronia.
3. Para cada troca, adicione o outro ângulo na v2 com `start` na timeline e `in_point`/`out_point` pelo offset do marcador. A v2 cobre a v1 enquanto ativa.
4. Ajuste com `trim_timeline_clip`; use `move_timeline_clip` só para deslocar.
5. O render mistura o áudio de todas as faixas de vídeo. Com áudio mestre na v1, use `volume=0` na v2. Se outro ângulo dominar um trecho, divida a v1 e zere o volume só desse segmento.
6. Use `split_timeline_clip` na v1 só para separar áudio ou criar corte seco.
7. Valide, renderize prévia 360p e confira sincronia visual e sonora.
8. Exporte após aprovar a prévia.

## 5. Critérios e parâmetros
- Mantenha `speed=1`; velocidades diferentes quebram a sincronia.
- Cada fragmento da v2 deve caber na base e cobrir exatamente a janela desejada.
- Evite cortes menores que 1 s; troque em pausas, reações ou mudanças de fala.
- A única transição é fade; use corte seco.
- `volume=0` no overlay é obrigatório se o áudio mestre vier da v1.
- Use o fps dos arquivos; misturar 24 e 30 fps gera movimento irregular.

## 6. Erros comuns
- Colocar o ângulo B inteiro na v2 e esperar que apareça só às vezes; sem keyframes, ele cobre a v1 todo o tempo.
- Esquecer o volume e ouvir dois áudios defasados.
- Calcular `start` pelo tempo do arquivo em vez do tempo da timeline.
- Usar `split_timeline_clip` com tempo do arquivo; ele corta no tempo da timeline.
- Mover a base depois dos overlays e perder o alinhamento.
- Julgar nitidez pela prévia 360p; ela serve para ritmo.

## 7. Checklist de qualidade
- [ ] v1 contínua, sem buracos, com o áudio mestre.
- [ ] Cada troca tem fragmento na v2 com início e fim corretos.
- [ ] Nenhum overlay passa da base.
- [ ] Áudio de uma só fonte por trecho, sem eco.
- [ ] Sincronia conferida em pelo menos três momentos.
- [ ] `validate_timeline` sem erros; prévia aprovada com QC.

## 8. Validação objetiva
`validate_timeline` deve retornar `ok: true` sem `severity: error`. Em `check_render_job`, confirme `status: done`, `qc.ok: true`, duração dentro de 0,5 s ou 1/fps e `av_start_delta` até 0,15 s. Isso prova alinhamento de streams, não sincronia de conteúdo; o conteúdo se confere na prévia.

## 9. Limitações atuais do ClipMind
Não há sincronização automática, detecção de claque, waveform, agrupamento multicâmera, troca por atalho nem keyframes. Não é possível separar áudio do vídeo. O fluxo é manual, com v2 como sobreposição. Para automatizar faltaria análise de áudio por correlação ou fingerprint, modelo de grupo com ângulo ativo por trecho, ferramenta de troca e suporte no renderizador. Sem isso, não prometa sincronização nem troca automática.

## 10. Ferramentas e skills relacionadas
Ferramentas: `inspect_edit_project`, `add_timeline_clip`, `trim_timeline_clip`, `split_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`. Skills: `export-and-delivery`, `render-diagnostics` e `timeline-debugging`.
