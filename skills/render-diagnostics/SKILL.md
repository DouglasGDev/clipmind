---
name: render-diagnostics
title: Diagnóstico de renderização
description: Investigue jobs travados, falhos ou cancelados, leia o log do FFmpeg e o QC para separar timeline, ambiente e bug.
triggers: render falhou, job travado, cancelar render, log ffmpeg, sem áudio no render, quadro preto, duração errada, qc reprovado, bug de render
tools: inspect_edit_project, validate_timeline, configure_edit_project, render_timeline, check_render_job, list_editor_skills, load_editor_skill
---

## 1. Objetivo
Diagnosticar uma renderização com evidências: estado do job, erro do FFmpeg, QC e timeline. Decidir se o problema é da timeline, do ambiente ou um bug do ClipMind.

## 2. Quando usar
Use com job `queued`/`running` sem progresso, `error`, cancelado, sem arquivo, duração errada, quadro preto, sem áudio, ou prévia e export divergentes.

## 3. Diagnóstico antes de editar
- `check_render_job(job_id)`: status, progresso, mensagem, erro e QC.
- Status: `queued`, `running`, `done`, `error`, `cancelled`.
- `validate_timeline` e `inspect_edit_project`: erros, duração e mídia.
- Confirme disco, permissão em `output/` e FFmpeg no PATH.
- "Tarefa não encontrada": id errado ou job antigo podado.

## 4. Procedimento
1. `queued`: servidor ocupado; sem fila persistente.
2. `running` sem progresso: veja CPU e disco; espere antes de cancelar.
3. Cancelar: interface ou API, sem ferramenta; vira `cancelled` e o parcial é apagado.
4. `error`: leia o fim do log; ache a linha antes de `Conversion failed!`.
5. Classifique: disco, caminho/permissão, encoder, memória, mídia, timeline ou FFmpeg ausente.
6. Duração diferente: compare com o projeto; tolerância 0,5 s ou 1/fps.
7. Preto: buracos na v1, fades e trechos sem overlay; fundo preto.
8. Áudio ausente: confirme se era esperado; sem fonte, sai silêncio e `audio_silent`.
9. Prévia × export: 360p e CRF próprio; compare duração, fps, enquadramento e áudio, não bitrate.
10. Corrija, valide e repita em prévia; exporte após job limpo.
11. Registre job_id, projeto, erro e medições no bug.

## 5. Critérios e parâmetros
- `done` + `qc.ok: true` é sucesso; avisos podem coexistir.
- Progresso: 95 no encode, 96 na validação, 100 no fim.
- Duração: aviso acima de max(0,5 s, 1/fps); fps acima de 0,05.
- Áudio esperado e ausente: erro `audio_missing`.
- Preto: ≥0,5 s com `pix_th=0.10`.
- Loudness < -60 LUFS, pico > -0,1 dBFS e sincronia > 0,15 s: avisos.
- Repita uma vez após corrigir.

## 6. Erros comuns
- Dizer que terminou sem consultar o job.
- Repetir o render sem corrigir a causa.
- Ler `Conversion failed!` e ignorar a linha anterior, que traz o motivo.
- Todo preto não é bug; buracos e fades produzem preto.
- Confundir artefato da prévia 360p com perda de qualidade.
- Cancelar e reenviar já, criando jobs concorrentes.
- Editar o projeto durante o render e comparar com snapshot antigo.
- Tratar `qc` ausente como aprovação.

## 7. Checklist de qualidade
- [ ] job_id e status final conhecidos.
- [ ] Erro do FFmpeg lido até a causa.
- [ ] Validação sem erros antes da nova tentativa.
- [ ] Disco e caminho conferidos.
- [ ] Duração, fps, resolução, áudio e sincronia medidos.
- [ ] Preto e loudness avaliados no contexto.
- [ ] Prévia aprovada antes do export.
- [ ] Evidências salvas para bug.

## 8. Validação objetiva
Sucesso: `status: done`, `qc.ok: true`, arquivo existente e não vazio. Em `measurements`, confira `duration`, `width`, `height`, `fps`, `has_audio`, `loudness_lufs`, `lra_lu`, `true_peak_dbfs`, `black_ranges` e `av_start_delta`. QC técnico não é narrativa: ele não vê conteúdo, legenda ou intenção. Se `black_qc_skipped` ou `loudness_qc_skipped` aparecer, a análise falhou; não é sinal de arquivo limpo.

## 9. Limitações atuais do ClipMind
Não há timeout, fila persistente, retomada, checagem de disco, log completo na ferramenta, cancelamento pelas ferramentas, garantia de GPU, preview em tempo real nem QC de conteúdo. A prévia é 360p; para reduzi-la use a API/interface com `max_height`, não a ferramenta. Alternativas: cancelar na interface, liberar disco, encurtar a timeline e repetir em prévia. Para automatizar faltaria timeouts, fila persistente, log exposto e diagnóstico de ambiente.

## 10. Ferramentas e skills relacionadas
Ferramentas: `inspect_edit_project`, `validate_timeline`, `configure_edit_project`, `render_timeline`, `check_render_job`, `list_editor_skills`, `load_editor_skill`. Skills: `export-and-delivery`, `timeline-debugging`, `accessibility-and-quality-control` e `multicam-editing`.
