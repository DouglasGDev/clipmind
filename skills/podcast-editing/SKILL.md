---
name: podcast-editing
title: Edição de Podcast
description: Podcast com vozes equilibradas por volume de clipe, fades e alinhamento manual; sem transcrição, remoção de silêncio nem faixa a2.
triggers: podcast, episódio, entrevista, convidado, diálogo, vozes, silêncio, narração
tools: create_edit_project, inspect_edit_project, add_timeline_clip, add_timeline_subtitles, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, move_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Quando usar
- Episódio de conversa, entrevista ou mesa com 2+ participantes.
- O áudio é o centro; vídeo fixo ou carta.
- Não espere multicam automático nem sync por waveform: não existem.

## 2. Objetivo
Entregar diálogo claro com vozes equilibradas, pausas e erros removidos manualmente, transições por fade e capítulos marcados. O medidor é o QC (loudness/peak); trechos e sincronia vêm do usuário e de tempos medidos.

## 3. Entradas necessárias
- Arquivos por participante com caminho absoluto; a duração real vem do probe das ferramentas.
- Timecodes de pausas/erros a cortar ou critérios descritos ("tirar gagueiros do take 2") — descrição, não audição.
- Estrutura: cold open, blocos, outro, duração alvo.
- Meta: -14 LUFS e pico ≤ -1 dBTP.

## 4. Ferramentas disponíveis
`create_edit_project`, `inspect_edit_project`, `add_timeline_clip`, `add_timeline_subtitles`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `move_timeline_clip`, `set_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.

## 5. Fluxo passo a passo
1. Projeto 1920x1080@30; confirme as faixas com `inspect_edit_project`.
2. Camadas de áudio reais: `a1` é a única faixa de áudio (não há ferramenta para criar `a2`), mais o áudio embutido em `v1`/`v2`. Ex.: apresentador no vídeo de `v1`, convidado em `a1`, trilha só embutida no vídeo ou pre-mixada fora.
3. Alinhe gravações separadas manualmente: leia durações e tempos devolvidos por `add_timeline_clip`/`inspect_edit_project`, marque o ponto comum (clap) e posicione com `move_timeline_clip(start=...)`.
4. Corte erros com `split_timeline_clip` + `delete_timeline_clip(confirm=true, ripple=true)`; ripple move só a faixa editada; ajuste as outras.
5. Equilibre vozes com `set_timeline_clip(volume=...)` por clipe: 0,8–1,4, diferença ≤ 3 dB (+6 dB ≈ ×2).
6. Fades: 1–2 s no início, 2–3 s no fim, 0,3–0,6 s entre blocos; `fade_in`/`fade_out` atingem áudio e vídeo.
7. Capítulos com `add_timeline_marker` (primeiro em 0; blocos ≥ 10 s); copie os tempos para a descrição do episódio.
8. Legenda opcional com `.srt` via `add_timeline_subtitles`. Valide, prévia, confira loudness/peak e exporte.

## 6. Regras obrigatórias
- Nunca dizer que "ouvi" ou detectei silêncios: sem transcrição e sem corte automático.
- `transition_type="fade"` é só imagem; para áudio use `fade_in`/`fade_out`.
- Ripple em uma faixa sem mexer as outras quebra a sincronia; sempre reinspecionar.
- Não há EQ, compressor, denoiser nem normalização: trate fora ou aceite o ruído.
- Não sobreponha clipes na mesma `a1`; dois microfones simultâneos exigem um embutido em vídeo.

## 7. Critérios de qualidade
- QC: loudness -14 LUFS ±1, true peak ≤ -1 dBTP, `has_audio=true`, delta A/V ≤ 0,15 s.
- Vozes com ≤ 3 dB entre si; música 12–18 dB abaixo.
- Sem cliques nem preto > 0,5 s; fades simétricos nos blocos.
- Validação `ok=true`, prévia revisada por humano e QC de exportação aprovado.

## 8. Erros comuns
- Prometer multicam ou sincronismo automático de gravações.
- Corrigir só a voz baixa até a outra clipar; reavaliar o mix inteiro.
- Tentar dois microfones ao mesmo tempo em `a1` (colisão).
- Confiar no delta A/V do QC como prova de sincronia de conteúdo.
- Deixar pausa longa esperando que "a ferramenta tire sozinha" — não tira.

## 9. Limitações do sistema atual
Sem transcrição/Whisper, remoção de silêncio, detecção de falante, nivelação, ducking, EQ/compressor/denoiser, waveform, beat, keyframes, LUTs, rastreamento e sync automático. Só existe a faixa `a1`; não há ferramenta para criar faixas de áudio extras. Transição é só fade e velocidade é constante. Faça o equivalente manual (split + delete com ripple, volume por clipe, offsets medidos) e informe isso na resposta, sem fingir automação.

## 10. Exemplo de uso
Usuário: "Podcast de 40 min; `host.mp4` com voz embutida e `convidado.mp4`; corte erros em 00:07:12 e 00:23:40."
1. `add_timeline_clip(track="v1", source="host.mp4", volume=1.0)`.
2. `add_timeline_clip(track="a1", source="convidado.mp4", start=<offset do clap>)`, conferindo o tempo devolvido.
3. `split_timeline_clip(at=432)` → `delete_timeline_clip(confirm=true, ripple=true)` nas duas faixas.
4. `set_timeline_clip(volume=0.9)` nos clipes mais altos; fades de 1,5 s no bloco final.
5. `validate_timeline` → prévia → `check_render_job` (loudness) → exporte. Declare: alinhamento por offset medido, sem sync automático e sem `a2`.
