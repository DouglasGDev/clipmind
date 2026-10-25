---
name: export-and-delivery
title: Exportação e entrega
description: Fluxo de prévia para exportação H.264/AAC, escolha de CRF, consistência de resolução e fps, QC e checklist de entrega.
triggers: exportar vídeo, renderizar, entrega final, youtube, shorts, crf, h264, mp4, qualidade de exportação, publicar
tools: inspect_edit_project, configure_edit_project, validate_timeline, render_timeline, check_render_job, load_editor_skill
---

## 1. Objetivo
Entregar um MP4 H.264/AAC íntegro, com resolução, fps e qualidade verificadas. A prévia serve para aprovar; a exportação serve para publicar. Nunca trate a prévia 360p como arquivo final.

## 2. Quando usar
Antes de publicar no YouTube, Shorts ou outra plataforma, ao gerar versão menor, ao trocar formato/resolução ou ao repetir uma entrega. Não use para upload automático: o ClipMind não publica.

## 3. Diagnóstico antes de editar
- `inspect_edit_project`: nome, resolução, fps, duração e clipes.
- `validate_timeline`: corrija todo `error` antes de renderizar.
- Confirme que a mídia existe e que o áudio está presente.
- Defina a especificação: 1920x1080 16:9, 1080x1920 9:16, fps do projeto e duração.
- Verifique espaço em disco e o nome desejado. A saída vai para `output/` e nunca sobrescreve.

## 4. Procedimento
1. Valide a timeline.
2. Renderize prévia com `render_timeline(preview=true)` e acompanhe com `check_render_job` até `status: done`.
3. Leia o QC e assista à prévia. Aprove conteúdo, ritmo, legenda e áudio.
4. Se o destino exigir outra proporção, ajuste com `configure_edit_project` antes do export; o render reenquadra os clipes.
5. Exporte com `render_timeline(preview=false, format="mp4", crf=...)` e um `filename` descritivo, sem extensão.
6. Não afirme que terminou sem `status: done`.
7. Confira `qc.ok` e as medições; resolva avisos relevantes e só então entregue.
8. Se o nome existir, o ClipMind cria `_2`, `_3`; não tente forçar sobrescrita.

## 5. Critérios e parâmetros
- MP4, H.264, AAC e `faststart`; padrão para YouTube e web.
- CRF 18 para alta qualidade; 23 para equilíbrio; 28 para cópia pequena. CRF 0 usa o padrão de exportação (20).
- Resolução e fps iguais aos do projeto e coerentes com a fonte.
- YouTube: 1920x1080, 16:9, 24–60 fps. Shorts: 1080x1920, 9:16, duração curta conforme o limite atual.
- Áudio presente com fala; -14 LUFS e true peak até -1 dBFS.
- Sem presets além de formato, resolução, fps e CRF; GPU pode cair para CPU.

## 6. Erros comuns
- Exportar antes de assistir à prévia.
- Entregar o `_preview` 360p como final.
- Usar CRF 18 por padrão e gerar arquivo enorme.
- Exportar em fps diferente do projeto e estranhar o movimento.
- Mudar a resolução depois de enquadrar títulos e legendas.
- Esperar sobrescrita de arquivo existente.
- Repetir encodes e perder qualidade.
- Prometer upload, thumbnail ou metadados.

## 7. Checklist de qualidade
- [ ] Timeline sem erros; avisos avaliados.
- [ ] Prévia aprovada em conteúdo, áudio e legenda.
- [ ] Resolução, fps e proporção corretos para o destino.
- [ ] Áudio presente e sem clipping.
- [ ] Legendas queimadas quando necessárias.
- [ ] Nome claro e versão identificável.
- [ ] Job `done`, `qc.ok: true`, medições conferidas.
- [ ] Arquivo reproduzido do início ao fim.

## 8. Validação objetiva
No `check_render_job`, exija `status: done` e `qc.ok: true`. Confira `duration` dentro de 0,5 s ou 1/fps, proporção do projeto, `fps` com diferença máxima de 0,05, `has_audio`, `loudness_lufs`, `true_peak_dbfs`, `black_ranges` e `av_start_delta` até 0,15 s. A prévia tem resolução proporcional menor; o QC aceita isso, mas não vale como entrega.

## 9. Limitações atuais do ClipMind
Não há presets de YouTube/Shorts além de formato, resolução, fps e CRF; não há upload, agendamento, thumbnail, metadados ou legendas separadas. A prévia é sempre 360p. O encode por GPU pode cair para CPU, sem garantia de velocidade. Não há compressão por tamanho-alvo, dois passes nem retomada. Alternativas: publicar fora, comprimir externamente e gerar capa/metadados em outra ferramenta. Para automatizar faltaria catálogo de presets, upload autenticado e validação de política de cada serviço.

## 10. Ferramentas e skills relacionadas
Ferramentas: `inspect_edit_project`, `configure_edit_project`, `validate_timeline`, `render_timeline`, `check_render_job`. Skills: `render-diagnostics` para jobs com erro, `accessibility-and-quality-control` para legenda e QC, `timeline-debugging` para validação e `multicam-editing` para ângulos.
