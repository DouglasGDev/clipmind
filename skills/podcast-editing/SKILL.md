---
name: podcast-editing
title: Edição de Podcast
description: Podcast com vozes equilibradas por volume por clipe, pausas medidas por FFmpeg e corte manual; sem transcrição nem faixa a2.
triggers: podcast, episódio, entrevista, convidado, diálogo, vozes, silêncio, narração
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Quando usar
- Episódio de conversa, entrevista ou mesa com 2+ participantes.
- O áudio é o centro; vídeo fixo ou carta.
- Não espere multicam automático nem sync por waveform: não existem.

## 2. Objetivo
Entregar diálogo claro com vozes equilibradas, pausas e erros removidos manualmente, transições por fade e capítulos marcados. O medidor é `analyze_timeline_clip` por clipe (loudness, pausas) mais o QC do render; texto falado e sincronia vêm do usuário e de tempos medidos.

## 3. Entradas necessárias
- Arquivos por participante com caminho absoluto; a duração real vem do probe das ferramentas.
- Pausas: mede com `analyze_timeline_clip(project_id, clip_id, kind="silence", noise=-30, min_pause=0.5)`. Erros de fala e trechos vêm do usuário ou dos timecodes que ele passa — não há transcrição.
- Estrutura: cold open, blocos, outro, duração alvo.
- Meta: -14 LUFS e pico ≤ -1 dBTP.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_subtitles`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`, `analyze_timeline_clip`, `clear_timeline_annotations`.

## 5. Fluxo passo a passo
1. Projeto 1920x1080@30; confirme as faixas com `inspect_edit_project`.
2. Camadas de áudio reais: `a1` é a única faixa de áudio (não há ferramenta para criar `a2`), mais o áudio embutido em `v1`/`v2`. Ex.: apresentador no vídeo de `v1`, convidado em `a1`, trilha só embutida no vídeo ou pre-mixada fora.
3. Alinhe gravações separadas manualmente: leia durações e tempos devolvidos por `add_timeline_clip`/`inspect_edit_project`, marque o ponto comum (clap) e posicione com `move_timeline_clip(start=...)`.
4. Meça as pausas antes de cortar: `analyze_timeline_clip(project_id, clip_id, kind="silence", noise=-30, min_pause=0.5)` devolve `start`/`end` em tempo de timeline e `source_start`/`source_end` no arquivo. Com `apply_candidates=true` elas viram regiões do grupo `pausas`, num único undo, para o humano revisar na timeline e no painel "Análise".
5. Corte erros e pausas aprovadas com `split_timeline_clip` + `delete_timeline_clip(confirm=true, ripple=true)`; ripple move só a faixa editada; ajuste as outras. Para descartar a sugestão: `clear_timeline_annotations(project_id, group="pausas")` — marcadores feitos à mão ficam.
6. Equilibre vozes medindo: `analyze_timeline_clip(project_id, clip_id, kind="loudness")` por clipe devolve `integrated_lufs`, `lra_lu`, `true_peak_dbfs`; compare com a meta e ajuste `set_timeline_clip(volume=...)` (0,8–1,4, diferença ≤ 3 dB, +6 dB ≈ ×2), depois meça de novo.
7. Fades: 1–2 s no início, 2–3 s no fim, 0,3–0,6 s entre blocos; `fade_in`/`fade_out` atingem áudio e vídeo.
8. Capítulos com `add_timeline_marker` (primeiro em 0; blocos ≥ 10 s); copie os tempos para a descrição do episódio.
9. Legenda opcional com `.srt` via `add_timeline_subtitles`. Valide, prévia, confira loudness/peak do render e exporte.

## 6. Regras obrigatórias
- Pausa só existe se saiu da medição: cite os intervalos que `analyze_timeline_clip(kind="silence")` devolveu. Nunca invente tempo de pausa nem diga que "ouvi" ou transcrevi fala — não há transcrição nem detecção de falante, e a análise não corta.
- `transition_type="fade"` é só imagem; para áudio use `fade_in`/`fade_out`.
- Ripple em uma faixa sem mexer as outras quebra a sincronia; sempre reinspecionar.
- Não há EQ, compressor, denoiser nem normalização: trate fora ou aceite o ruído.
- Não sobreponha clipes na mesma `a1`; dois microfones simultâneos exigem um embutido em vídeo.

## 7. Critérios de qualidade
- Por clipe: `analyze_timeline_clip(kind="loudness")` com `integrated_lufs` perto da meta e `true_peak_dbfs` folgado, antes de somar as vozes.
- QC do render: loudness -14 LUFS ±1, true peak ≤ -1 dBTP, `has_audio=true`, delta A/V ≤ 0,15 s.
- Vozes com ≤ 3 dB entre si; música 12–18 dB abaixo.
- Sem cliques nem preto > 0,5 s (`black_ranges` do QC); fades simétricos nos blocos.
- Validação `ok=true`, prévia revisada por humano e QC de exportação aprovado.

## 8. Erros comuns
- Prometer multicam ou sincronismo automático de gravações.
- Corrigir só a voz baixa até a outra clipar; reavaliar o mix inteiro.
- Tentar dois microfones ao mesmo tempo em `a1` (colisão).
- Confiar no delta A/V do QC como prova de sincronia de conteúdo.
- Deixar pausa longa sem medir e depois agir como se ela tivesse aparecido sozinha: a pausa vem de `analyze_timeline_clip(kind="silence")`, e o corte continua manual.

## 9. Limitações do sistema atual
Existe medição: `analyze_timeline_clip` roda FFmpeg num clipe e devolve pausas (`kind="silence"`, com `noise` em dB e `min_pause` em s), trocas de cena com score (`kind="scenes"`, `threshold` 1–100, tempo na timeline e no arquivo) e três números de áudio (`kind="loudness"`: LUFS integrado, LRA em LU, true peak em dBFS). Com `apply_candidates=true` pausas viram regiões (grupo `pausas`) e cenas viram marcadores (grupo `cenas`), num único undo; `clear_timeline_annotations` remove só esse grupo. O QC do render reporta `loudness_lufs`, `lra_lu`, `true_peak_dbfs` e `black_ranges`.

Não existe: transcrição/Whisper, timestamps por palavra, identificação de falante, corte automático de pausa (a análise propõe, `split`+`delete` cortam), nivelação/normalização automática, ducking, EQ/compressor/denoiser, waveform, curva de pico por instante, beat, keyframes, LUTs, rastreamento e sync automático. Só há a faixa `a1`; não há ferramenta para criar faixas de áudio extras e o limitador é fixo em 0,95 (≈ -0,45 dBFS). Transição é só fade e velocidade é constante. Faça o equivalente manual (medir, split + delete com ripple, volume por clipe, offsets medidos) e informe isso na resposta, sem fingir automação.

## 10. Exemplo de uso
Usuário: "Podcast de 40 min; `host.mp4` com voz embutida e `convidado.mp4`; corte erros em 00:07:12 e 00:23:40 e tire as pausas longas."
1. `add_timeline_clip(track="v1", source="host.mp4", volume=1.0)`.
2. `add_timeline_clip(track="a1", source="convidado.mp4", start=<offset do clap>)`, conferindo o tempo devolvido.
3. `analyze_timeline_clip(project_id, clip_id, kind="silence", noise=-30, min_pause=0.8, apply_candidates=true)` em cada voz: regiões do grupo `pausas` para o humano aprovar.
4. `analyze_timeline_clip(project_id, clip_id, kind="loudness")` por voz: `integrated_lufs`, `lra_lu`, `true_peak_dbfs` antes de qualquer volume.
5. `split_timeline_clip(at=432)` → `delete_timeline_clip(confirm=true, ripple=true)` nas duas faixas, só nos pontos aprovados.
6. `set_timeline_clip(volume=0.9)` nos clipes mais altos, meça de novo; fades de 1,5 s no bloco final.
7. `validate_timeline` → prévia → `check_render_job` (loudness do arquivo) → exporte. Declare: alinhamento por offset medido, pausas vindas de medição, sem transcrição, sem sync automático e sem `a2`.
