---
name: professional-cutting
title: Corte Profissional
description: Decisões de entrada e saída, ripple, roll, slip e slide para cortes limpos e sem quadros de flash.
triggers: corte, corte seco, ripple, roll, slip, slide, aparar clipe, J-cut, L-cut, quadro de flash
tools: inspect_edit_project, trim_timeline_clip, split_timeline_clip, move_timeline_clip, fine_timeline_edit, delete_timeline_clip, duplicate_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Objetivo
Executar cortes precisos: escolher a borda e a operação certas, preservar handles e revisar o resultado. O foco é ritmo e continuidade, não reestruturar a história.

## 2. Quando usar
- Encurtar trechos ou fechar buracos.
- Ajustar fronteiras entre clipes montados.
- Criar J/L cuts com áudio em a1.
- Revisar cortes e flash frames.

## 3. Diagnóstico antes de editar
1. Chame `inspect_edit_project` e anote ids, `start`, duração, in/out e faixa.
2. Converta timeline em tempo do arquivo: a velocidade 1, `in = clip.in + (ponto - clip.start)`; com outra, multiplique o deslocamento por `speed`.
3. Confirme os cortes com o usuário, roteiro ou ação visível. Sem transcrição, detecção de silêncio ou waveform, não adivinhe fala.
4. Rode `validate_timeline` e registre colisões, buracos e fades.
5. Garanta handles de 0,3–0,5 s antes e depois do corte.

## 4. Procedimento
1. Carregue esta skill e inspecione; marque os pontos-alvo se ajudar.
2. Escolha a operação (`fine_timeline_edit` para roll, slip e slide):
  - `trim_timeline_clip`: apara no tempo do arquivo; `ripple=true` fecha o buraco, `false` preserva o sincronismo.
  - `roll`: move a fronteira de clipes encostados; duração fixa e handles nos dois.
  - `slip`: troca o trecho sem mover; mesma duração e material antes/depois.
  - `slide`: move o clipe e ajusta vizinhos encostados.
3. Para remover o meio: divida com `split_timeline_clip` e exclua com `delete_timeline_clip(confirm=true)` após aval.
4. Corte na ação 2–4 frames após o início do movimento ou no impacto; não corte fala sem handle.
5. J/L: vídeo em v1, áudio em a1; `set_timeline_clip(volume=0)` no vídeo evita som duplo. J = áudio antes; L = depois. Sem vínculo: mova os dois lados e reinspecione.
6. Revise a prévia, corrija e valide antes de exportar.

## 5. Critérios e parâmetros
- 1 frame: 0,042 s a 24 fps, 0,033 a 30, 0,017 a 60; use deltas de 0,03–0,05 s.
- Duração mínima de corte: 0,3 s; reação curta, 0,5–1,0 s.
- Handles: 0,3–0,5 s; nunca apare o fim exato.
- J cut: áudio 0,3–0,7 s adiantado. L cut: áudio 0,5–1,0 s atrasado.
- Ripple desloca só a faixa editada.
- Roll exige contato e handles; slide, vizinhos encostados.
- Evite clipes <0,3 s: risco de flash frame.

## 6. Erros comuns
- Aparar in/out pensando que são tempos da timeline.
- Usar ripple em vídeo sem corrigir áudio separado.
- Aplicar roll sem clipe seguinte encostado ou sem handle.
- Usar slip para mudar a duração ou slide com buraco dos lados.
- Deixar 1–2 frames de sobra no corte, criando flash frame.
- Excluir sem confirmação ou cortar por relógio.

## 7. Checklist de qualidade
- [ ] Cada corte tem início, fim e handles intencionais.
- [ ] A operação escolhida produz o efeito esperado.
- [ ] Sem flash frames, buracos ou colisões.
- [ ] Prévia revisada e QC aprovado.

## 8. Validação objetiva
- `validate_timeline` sem erros e sem sobreposição.
- Comparar os cortes planejados com `start`/duração no inspect.
- Duração coerente: ripple e slide alteram; roll e slip mantêm.
- `check_render_job` com `qc.ok=true`; sem preto ≥0,5 s não intencional e delta A/V ≤0,15 s.
- Flash frames e sincronia fina exigem revisão humana no export; a prévia 360p pode mascarar 1 frame.

## 9. Limitações atuais do ClipMind
Não há transcrição, detecção de silêncio, waveform, análise de fala nem clipes vinculados de áudio/vídeo. J/L cuts são alinhamentos manuais entre v1 e a1. Não há keyframes, rastreamento nem prévia em tempo real; a prévia é um render 360p. Para decisões finas, o humano fornece timecodes e revisa o export quadro a quadro.

## 10. Ferramentas e skills relacionadas
- Corte: `trim_timeline_clip`, `split_timeline_clip`, `fine_timeline_edit`, `delete_timeline_clip`.
- Apoio: `inspect_edit_project`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.
- Skills: `video-editor-core`, `transitions-and-keyframes`, `storytelling-and-pacing`.