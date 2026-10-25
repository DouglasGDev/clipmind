---
name: storytelling-and-pacing
title: Narrativa e Ritmo
description: Estrutura de hook a payoff, ritmo por gênero e marcadores para dar intenção à timeline.
triggers: narrativa, ritmo, hook, retenção, pacing, estrutura, short, aceleração, marcadores, progressão
tools: inspect_edit_project, add_timeline_marker, move_timeline_clip, trim_timeline_clip, split_timeline_clip, set_timeline_clip, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Objetivo
Planejar e executar a narrativa na timeline: hook, progressão, payoff e ritmo adequado ao formato. Decidir o que cortar antes de acelerar.

## 2. Quando usar
- Ao montar do zero ou reestruturar o corte.
- Quando o vídeo parece lento, repetitivo ou sem clareza.
- Para adaptar material longo a Shorts/Reels.
- Antes de aprovar a versão final.

## 3. Diagnóstico antes de editar
1. Chame `inspect_edit_project` e leia duração, ordem dos clipes e marcadores existentes.
2. Confirme formato, público, duração-alvo e mensagem principal. Não há métricas de retenção locais.
3. Mapeie os beats com roteiro ou indicações do usuário e confirme as bordas medindo: `analyze_timeline_clip(kind="silence")` devolve as pausas do clipe e `kind="scenes"` as trocas de cena, ambas em tempo de timeline. Sem transcrição, não adivinhe o conteúdo falado — o texto vem do usuário; a medição dá tempo, não palavra.
4. Identifique: hook nos primeiros 1–3 s, trechos sem informação nova, repetições e encerramento abrupto.
5. Verifique a base técnica: clipes ≥0,3 s, áudio presente, títulos legíveis.

## 4. Procedimento
1. Carregue esta skill e inspecione.
2. Defina o beat sheet com tempos exatos:
- Até 60 s: hook 0–2; contexto 2–8; progressão 8–35; virada 35–50; payoff 50–57; CTA 57–60.
- Longo: hook 0–10 s; setup 10–60 s; progressão com re-hook a cada 20–40 s; payoff no fim.
3. Marque os beats com `add_timeline_marker` e rótulos HOOK, SETUP, PROGRESSÃO, VIRADA, PAYOFF e CTA. As pausas e cenas medidas entram como candidatos (`apply_candidates=true`), nos grupos `pausas` e `cenas`; seus marcadores manuais ficam intactos e `clear_timeline_annotations` limpa só o grupo da análise.
4. Reordene e apare clipes para caber nos beats. Comece pelo hook, sem logo ou intro.
5. Varie a duração dos planos; evite ritmo uniforme. Segure o payoff 3–5 s.
6. Reforce retenção a cada 20–40 s (8–15 s em Shorts) com informação nova, enquadramento, B-roll aprovado ou título; não há detecção automática de destaque — as bordas medidas de pausa e cena só sugerem onde olhar.
7. Use `set_timeline_clip(speed=...)` só em transporte ou B-roll: 1,25–2,0×; em fala, 0,95–1,10×. A duração muda e pode colidir; ajuste vizinhos.
8. Retime os marcadores após mudanças, renderize prévia, valide e exporte.

## 5. Critérios e parâmetros
| Formato | Plano médio | Corte a cada | Duração alvo |
|---|---|---|---|
| Shorts/Reels | 0,8–2,5 s | 1,5–3 s | 15–60 s |
| Vlog/tutorial | 3–6 s | 4–8 s | 5–15 min |
| Talking head | 3–5 s | 4–8 s | 3–10 min |
| Documentário | 4–8 s | 6–12 s | 10–30 min |

- Hook: o mais forte nos primeiros 1–3 s.
- Re-hook: a cada 20–40 s em vídeos longos; 8–15 s em Shorts.
- Payoff: 3–5 s sem corte para o espectador absorver.
- Fala: 0,95–1,10×; nunca use 2× para esconder conteúdo fraco.
- Marcadores: no máximo um por beat; rótulos curtos e únicos.
- Evite cortes <0,3 s, fades longos e aceleração sem função narrativa.

## 6. Erros comuns
- Intro antes do hook ou hook enterrado no meio.
- Cortar tudo no mesmo intervalo e achatar o ritmo.
- Acelerar fala para caber na duração, prejudicando a clareza.
- Repetir a mesma informação com imagens diferentes.
- Deixar marcadores desatualizados após reordenar clipes.

## 7. Checklist de qualidade
- [ ] Hook claro nos primeiros 1–3 s.
- [ ] Beats marcados e na ordem prevista.
- [ ] Ritmo varia e o payoff tem respiro.
- [ ] Nenhuma aceleração gratuita de fala.
- [ ] Prévia e QC aprovados.

## 8. Validação objetiva
- Marcadores conferem com os tempos e rótulos planejados no inspect.
- Cortes por minuto: número de clipes de vídeo ÷ duração em minutos; comparar com o alvo do formato.
- Duração final dentro da meta e sem erro no `validate_timeline`.
- `check_render_job` com `qc.ok=true`; áudio e A/V dentro dos limites.
- Retenção real não é medida localmente: exige análise humana ou métricas externas.

## 9. Limitações atuais do ClipMind
`analyze_timeline_clip` mede um clipe por vez com FFmpeg: `kind="scenes"` (`scdet`) devolve as trocas de cena com score e os tempos da timeline e do arquivo, `kind="silence"` (`silencedetect`) devolve as pausas com início e fim, `kind="loudness"` (`ebur128`) devolve três números agregados do recorte (LUFS integrado, LRA em LU, true peak em dBFS). Com `apply_candidates=true` os candidatos viram marcadores (`cenas`) ou regiões (`pausas`) num único passo de undo, visíveis na timeline e no inspector "Análise", e `clear_timeline_annotations` remove o grupo; a medição não corta nada e não entende o que é dito. Não há transcrição, timecode por palavra, identificação de falante, waveform, curva de pico por momento, métricas de retenção nem detecção automática de destaque: o beat é decisão sua. Os marcadores de estrutura continuam manuais. Sem keyframes, rastreamento, multicam, cor além de brilho/contraste/saturação/gamma, processamento de áudio além de `afade` e `volume` por clipe (0–4) e sem prévia em tempo real — a prévia é um render 360p. Transição é só fade e a velocidade é constante 0,1–8.

## 10. Ferramentas e skills relacionadas
- Estrutura: `inspect_edit_project`, `add_timeline_marker`.
- Medição: `analyze_timeline_clip`, `clear_timeline_annotations`.
- Edição: `move_timeline_clip`, `trim_timeline_clip`, `split_timeline_clip`, `set_timeline_clip`.
- Entrega: `validate_timeline`, `render_timeline`, `check_render_job`.
- Skills: `professional-cutting`, `b-roll-planning`, `transitions-and-keyframes`.
