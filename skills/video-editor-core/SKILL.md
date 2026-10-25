---
name: video-editor-core
title: Núcleo do Editor de Vídeo
description: Modelo mental de projeto, faixas e ordem segura de operações na timeline do ClipMind.
triggers: timeline, projeto de edição, faixas, organização, validar timeline, renderizar, prévia, marcadores
tools: create_edit_project, inspect_edit_project, configure_edit_project, add_timeline_clip, add_timeline_text, add_timeline_subtitles, validate_timeline, render_timeline, check_render_job, add_timeline_marker, list_editor_skills, load_editor_skill
---

## 1. Objetivo
Operar a timeline não destrutiva do ClipMind, que guarda referências e parâmetros sem alterar o original. Escolha a faixa certa, faça mudanças pequenas e comprove o resultado antes de exportar.

## 2. Quando usar
- No início da edição e após cada lote.
- Antes de prévia/exportação e ao diagnosticar falhas.
- Ao mudar resolução, fps ou destino.

## 3. Diagnóstico antes de editar
1. Chame `inspect_edit_project` e leia duração, faixas, ids, tempos e avisos.
2. Rode `validate_timeline`: erro impede render; aviso exige revisão.
3. Confirme os arquivos citados pelo usuário; nunca invente caminhos, clipes ou ids.
4. Trabalhe em `HH:MM:SS.mmm`; as ferramentas recebem segundos, não frames.
5. Localize a faixa (v1 base, v2 sobreposição, t1 títulos, s1 legendas, a1 áudio) e evite colisão na mesma faixa; entre faixas é permitido.

## 4. Procedimento
1. Carregue esta skill e a específica com `load_editor_skill`.
2. Inspecione antes de qualquer mudança.
3. Crie projeto só se necessário, com dimensões pares e fps coerente (1920x1080@30 ou 1080x1920@30).
4. Monte v1; sem `start`, entra no fim da faixa. `in_point`/`out_point` são segundos do arquivo, não da timeline.
5. Use v2 para sobreposição, a1 para áudio, t1 para títulos e s1 para legendas .srt/.vtt/.ass.
6. Faça operações pequenas e reinspecione a cada lote.
7. Valide: elimine os erros e avalie cada aviso.
8. Renderize prévia (`preview=true`) e acompanhe com `check_render_job` até `status=done` e `qc.ok=true`.
9. Revise, corrija, valide e exporte com `preview=false`; confirme o QC final antes de concluir.

## 5. Critérios e parâmetros
- Clipe mínimo: 0,05 s; para qualidade, use ≥0,3 s.
- Uma faixa não aceita dois clipes no mesmo instante. Mover não fecha buraco; apare com `trim_timeline_clip(ripple=true)` ou use `slide`.
- Fades: soma ≤ duração. Transição fade: ≤ metade do clipe.
- Velocidade 0,1–8; altera a duração e pode colidir.
- Volume 0–4; sem ducking automático.
- Prévia 360p/CRF 28; exportação CRF 20 na resolução do projeto.
- Marcadores: antes de ripple grande e em aprovações.
- Exclusão só com `confirm=true` após aval explícito.

## 6. Erros comuns
- Editar sem inspecionar e usar id/tempo desatualizado.
- Confundir tempo do arquivo (in/out) com tempo da timeline (start).
- Esperar que mover feche buraco ou que aparar mova as outras faixas.
- Sobrepor na mesma faixa ou duplicar áudio entre v1 e a1.
- Exportar antes da prévia ou concluir sem consultar o job.
- Mudar resolução no fim sem revisar títulos e legendas.

## 7. Checklist de qualidade
- [ ] Faixas e ids conferidos; zero erros na validação.
- [ ] Sem colisões ou buracos involuntários.
- [ ] Áudio esperado presente e sem duplicação.
- [ ] Títulos e legendas legíveis na prévia.
- [ ] Prévia revisada e QC aprovado; exportação conferida.

## 8. Validação objetiva
- `validate_timeline` com `ok=true` e nenhum erro.
- `check_render_job` com `status=done`, `qc.ok=true` e arquivo gerado.
- Duração dentro de 0,5 s (ou 1/fps); proporção correta; fps ±0,05.
- Áudio presente quando esperado; sem aviso de vídeo mudo.
- Sem preto ≥0,5 s não intencional; loudness > -60 LUFS; true peak ≤ -0,1 dBFS; delta A/V ≤ 0,15 s.

## 9. Limitações atuais do ClipMind
Não há prévia em tempo real: é um render leve de 360p. Não existem transcrição, detecção de silêncio, keyframes/curvas, rastreamento, multicam, LUTs, EQ/compressor/denoiser, waveform, B-roll automático nem capítulos. Faixas: v1, v2, t1, s1, a1. O humano fornece timecodes/arquivos ou usa editor externo.

## 10. Ferramentas e skills relacionadas
- Projeto/conteúdo: `create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_text`, `add_timeline_subtitles`.
- Edição/entrega: `trim_timeline_clip`, `split_timeline_clip`, `fine_timeline_edit`, `set_timeline_clip`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Skills: `professional-cutting`, `storytelling-and-pacing`, `transitions-and-keyframes`, `b-roll-planning`.
