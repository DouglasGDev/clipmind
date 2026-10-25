---
name: b-roll-planning
title: Planejamento de B-roll
description: Planejar inserções de B-roll com ponto, propósito e duração antes de tocar na timeline.
triggers: b-roll, inserção, cobertura, imagem de apoio, narração, plano de corte, v2, sobreposição, continuidade, material de apoio
tools: inspect_edit_project, add_timeline_clip, move_timeline_clip, trim_timeline_clip, set_timeline_clip, add_timeline_marker, analyze_timeline_clip, clear_timeline_annotations, validate_timeline, render_timeline, check_render_job
---

## 1. Objetivo
Planejar cada inserção com ponto, propósito, duração e tipo antes de editar. O ClipMind não busca nem baixa imagens: use só material fornecido e autorizado.

## 2. Quando usar
- Quando a narração precisar de ilustração, cobertura de jump cuts ou contexto.
- Para transições visuais.
- Quando pedirem onde colocar B-roll.

## 3. Diagnóstico antes de editar
1. Chame `inspect_edit_project` e liste ids, `start`, duração e faixa dos clipes.
2. Obtenha roteiro, descrição ou timecodes do usuário. Sem transcrição, não adivinhe a fala: o texto dito continua vindo do humano.
3. Meça o clipe com `analyze_timeline_clip`: `kind="silence"` dá as pausas reais (início/fim em tempo de timeline; ajuste `noise` e `min_pause`) e `kind="scenes"` dá as fronteiras de plano com score (`threshold` menor acha mais; o candidato traz o tempo da timeline e o do arquivo). É isso que ancora o plano em timecode, não a intuição.
4. Marque as lacunas sobre os intervalos medidos: trecho longo sem troca de cena (salto no mesmo plano), pausa cobrindo fala ou silêncio morto, explicação abstrata sem apoio visual.
5. Apresente os tempos medidos e só depois grave candidatos com `apply_candidates=true`: cenas viram marcadores `cenas`, pausas viram regiões `pausas`, num único undo. Candidato não é inserção. Se a sugestão não servir ou for refazer com outros parâmetros, `clear_timeline_annotations`.
6. Verifique a ocupação da v2 e os arquivos fornecidos. Sem material licenciado, entregue só o plano.
7. Confira marcadores existentes para não duplicar inserções.

## 4. Procedimento
1. Carregue esta skill, inspecione e cite os pontos em `HH:MM:SS.mmm`, tirados da medição (`analyze_timeline_clip`) ou do usuário.
2. Monte uma tabela por inserção: ponto, duração, propósito, tipo, arquivo/status e áudio.
- Exemplo: `00:00:12.400 | 3 s | ilustrar "produção" | detalhe | X aprovado | sem áudio`.
3. Apresente o plano e aguarde aprovação explícita; não altere nada antes.
4. Aprovado, use `add_timeline_clip(source=..., track="v2", start=..., in_point=..., out_point=...)`. Mantenha a v1 intacta.
5. Ajuste para 2–5 s, salvo necessidade narrativa; apare com `trim_timeline_clip` e alinhe com `move_timeline_clip`.
6. Se o áudio não deve entrar, use `set_timeline_clip(volume=0, fade_in=0.3, fade_out=0.3)`.
7. Preserve direção de olhar e movimento, cor, escala e ação. Não cubra fala importante nem lip sync.
8. Valide, renderize prévia e mostre ao usuário antes de exportar.

## 5. Critérios e parâmetros
- Toda inserção precisa de propósito: cobrir corte, ilustrar, contextualizar ou pontuar.
- Duração: detalhe 1,5–3 s; ação/estabelecimento 3–5 s; máximo 6 s sem informação nova.
- Entrada 0,2–0,4 s antes da menção; corte em fronteira de palavra, julgada na prévia (não há timestamp de palavra).
- Não cubra hook (1–3 s), payoff nem CTA.
- B-roll em 20–40% do tempo; evite mais de duas inserções seguidas.
- Use v2; não substitua a v1 sem aprovação.
- Áudio: volume 0 por padrão; sem ducking, EQ ou crossfade.
- Direitos: só arquivos fornecidos ou comprovadamente licenciados.

## 6. Erros comuns
- Inventar caminho, clipe ou material que não foi entregue.
- Baixar mídia sem autorização ou ignorar direitos autorais.
- Substituir a v1 sem aprovação.
- Cobrir diálogo importante ou o hook com imagem de apoio.
- Deixar inserções longas e repetitivas, sem função.
- Esquecer colisão na v2 ou áudio duplicado.
- Ignorar direção, cor e movimento entre planos.

## 7. Checklist de qualidade
- [ ] Cada inserção tem ponto, propósito, duração e fonte aprovada.
- [ ] v1 intacta e v2 sem sobreposição.
- [ ] Áudio e fades controlados.
- [ ] Continuidade visual revisada.
- [ ] Plano aprovado e prévia/QC conferidos.

## 8. Validação objetiva
- `inspect_edit_project` confirma início/fim e faixa de cada B-roll; a v1 permanece.
- `validate_timeline` sem erros ou sobreposição.
- Conferir a tabela planejada com os tempos reais; nenhum valor inventado.
- `check_render_job` com `qc.ok=true`; sem preto ≥0,5 s e áudio presente quando esperado.
- Proporção: soma das durações na v2 ÷ total.
- Continuidade e direitos exigem revisão humana; a prévia 360p não basta.

## 9. Limitações atuais do ClipMind
- `analyze_timeline_clip` mede um clipe por vez com FFmpeg: `kind="scenes"` (`scdet`) acha as fronteiras de plano com score, nos tempos da timeline e do arquivo; `kind="silence"` (`silencedetect`) acha pausas com início/fim; `kind="loudness"` (`ebur128`) dá LUFS integrado, LRA em LU e true peak em dBFS da janela do clipe. É o que ancora o plano de cobertura em timecode.
- Medir não é entender nem editar: a análise não corta. `apply_candidates=true` só escreve candidatos (marcadores `cenas`, regiões `pausas`) num único undo, sem tocar em item feito à mão; `clear_timeline_annotations(group="cenas")` remove só o grupo escrito. O julgamento de continuidade e a inserção seguem humanos, com `add_timeline_clip`, `trim_timeline_clip` e `move_timeline_clip`.
- Não existem: transcrição, texto da fala, timestamps por palavra, identificação de vozes; busca ou download automático de B-roll; análise do conteúdo da imagem (não lê quadro, rosto, objeto nem cor); rastreamento, reframe automático, sincronia multicam; waveform desenhada na timeline (a curva de pico por instante existe na análise `kind="peaks"`), detecção de highlights; LUT, EQ e qualquer outro filtro de áudio (só `afade` e `volume` 0–4); keyframes, rampa de velocidade, transição que não seja fade; prévia em tempo real (é render 360p).
- O humano fornece material licenciado, confirma direitos e aprova o plano; sem arquivo aprovado, entregue só o plano.

## 10. Ferramentas e skills relacionadas
- Diagnóstico: `inspect_edit_project`, `analyze_timeline_clip`, `clear_timeline_annotations`, `add_timeline_marker`.
- Inserção: `add_timeline_clip`, `move_timeline_clip`, `trim_timeline_clip`, `set_timeline_clip`.
- Entrega: `validate_timeline`, `render_timeline`, `check_render_job`.
- Skills: `storytelling-and-pacing`, `transitions-and-keyframes`, `video-editor-core`.
