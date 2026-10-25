---
name: timeline-debugging
title: Diagnóstico e correção de timeline
description: Interprete erros e avisos de validação e repare a timeline com a menor operação segura, sem exclusões impulsivas.
triggers: erro na timeline, validação, clipe sobreposto, mídia ausente, fora dos limites, timeline vazia, legenda ausente, sem áudio, corrigir timeline
tools: inspect_edit_project, validate_timeline, configure_edit_project, add_timeline_clip, move_timeline_clip, trim_timeline_clip, split_timeline_clip, fine_timeline_edit, set_timeline_clip, duplicate_timeline_clip, delete_timeline_clip, render_timeline, check_render_job
---

## 1. Objetivo
Restaurar a timeline com a menor mudança, preservando o trabalho e explicando a causa. Corrigir não é apagar: é devolver consistência a ids, tempos, mídia e configurações.

## 2. Quando usar
Use quando `validate_timeline` falhar, o render for recusado, houver sobreposição ou clipe fora do arquivo, mídia/legenda ausente, timeline vazia, áudio sumido ou transição longa.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: projeto, duração, erros e avisos.
2. `validate_timeline`: `severity`, `code`, `track_id` e `clip_id`.
3. Leia o código antes de agir.
4. Confira ids, `start`, `in`, `out`, `speed` e caminho.
5. Confirme a mídia no caminho absoluto.
6. Não edite sem saber o clipe e o campo errados.

## 4. Procedimento
1. `error` bloqueia; `warning` exige decisão; `info` contextualiza.
2. Mídia ausente: restaure no caminho original; se mudou, readicione no mesmo `start`/trecho e remova a antiga só com `confirm=true` e aval.
3. Sobreposição: mova o posterior ou corte o excesso; não apague o primeiro.
4. Fora dos limites: ajuste `in`/`out` para dentro da fonte.
5. Fade: soma ≤ duração; transição ≤ metade do clipe.
6. Legenda/título ausente: restaure, readicione ou preencha; remoção exige confirmação.
7. Vazia ou duração zero: adicione mídia ou restaure versão.
8. Settings: `configure_edit_project` com lados pares 16–7680/4320 e fps 1–240.
9. Sem áudio ou imagem: confirme a intenção; se não, adicione mídia.
10. Valide após cada operação; undo/redo e versões (30) são da interface/API.
11. Só então renderize prévia e consulte o job.

## 5. Critérios e parâmetros
- Uma correção por vez, validando em seguida.
- Prefira mover/cortar a readicionar; readicionar muda ids e duplica áudio.
- `ripple` só para fechar espaço; desloca os seguintes.
- `split.at` é tempo da timeline; `trim.in/out` é tempo da fonte.
- `fine_timeline_edit`: slip troca trecho, slide move clipe, roll move fronteira.
- Nunca use `delete_timeline_clip` para silenciar o validador.

## 6. Erros comuns
- Apagar o clipe "problemático" e perder conteúdo.
- Mover sem conferir colisão.
- Confundir tempo da timeline com tempo do arquivo.
- Ignorar que `speed` ≠ 1 muda a duração.
- Readicionar mídia sem remover a antiga, duplicando áudio.
- Tratar `warning` como erro ou `error` como detalhe.
- Renderizar sem validar e repetir o erro.
- Restaurar versão sem avisar.

## 7. Checklist de qualidade
- [ ] `validate_timeline` sem `error`.
- [ ] Todo `warning` explicado ou corrigido.
- [ ] Ids e tempos conferidos no inspect.
- [ ] Mídia e legendas acessíveis.
- [ ] Áudio e vídeo presentes quando esperados.
- [ ] Resolução e fps válidos.
- [ ] Prévia com QC aprovado.
- [ ] Usuário informado de exclusões/restaurações.

## 8. Validação objetiva
Códigos: `settings`, `no_tracks`, `track_type`, `duplicate_clip`, `clip_shape`, `clip_time`, `overlap`, `missing_source`, `missing_media`, `out_of_bounds`, `in_of_bounds`, `fade`, `transition`, `empty_text`, `missing_subtitles`, `empty_project`, `zero_duration`, `no_video`, `no_audio`. Sucesso: `ok: true` e job `done` com `qc.ok: true`; duração ±0,5 s ou 1/fps.

## 9. Limitações atuais do ClipMind
Não há relink automático, reparo automático, undo nas ferramentas, faixas aninhadas, keyframes ou mute por ferramenta. Undo em memória; 30 versões. Alternativas: restaurar no caminho antigo, usar undo/versões na interface e recriar o clipe com os tempos. Para automatizar faltaria relink por hash, reparos transacionais e undo/restore como ferramentas.

## 10. Ferramentas e skills relacionadas
Ferramentas: `inspect_edit_project`, `configure_edit_project`, `validate_timeline`, `move_timeline_clip`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `render_timeline`, `check_render_job`. Skills: `render-diagnostics`, `export-and-delivery` e `accessibility-and-quality-control`.
