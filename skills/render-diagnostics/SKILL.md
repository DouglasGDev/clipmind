---
name: render-diagnostics
title: Diagnóstico de renderização
description: Investigue jobs travados, falhos ou cancelados, leia o log do FFmpeg e o QC para separar timeline, ambiente e bug.
triggers: render falhou, job travado, cancelar render, log ffmpeg, sem áudio no render, quadro preto, duração errada, qc reprovado, bug de render
tools: inspect_edit_project, validate_timeline, configure_edit_project, render_timeline, check_render_job, list_editor_skills, load_editor_skill, analyze_timeline_clip, clear_timeline_annotations
---

## 1. Objetivo
Diagnosticar uma renderização com evidências: estado do job, erro do FFmpeg, QC e timeline. Decidir se o problema é da timeline, do ambiente ou um bug do ClipMind.

## 2. Quando usar
Use com job `queued`/`running` sem progresso, `error`, cancelado, sem arquivo, duração errada, quadro preto, sem áudio, ou prévia e export divergentes.

## 3. Diagnóstico antes de editar
- `check_render_job(job_id)`: status, progresso, mensagem, erro e QC.
- Status: `queued`, `running`, `done`, `error`, `cancelled`.
- `validate_timeline` e `inspect_edit_project`: erros, duração e mídia.
- `analyze_timeline_clip(project_id, clip_id, kind="loudness")` mede a fonte do clipe que aparece errado no render; `kind="scenes"` e `kind="silence"` conferem se o material já veio com o problema. A medição lê o arquivo, não o render: serve para comparar, não para acusar o encoder.
- Confirme disco, permissão em `output/` e FFmpeg no PATH.
- "Tarefa não encontrada": id errado ou job antigo podado.

## 4. Procedimento
1. `queued`: servidor ocupado; sem fila persistente.
2. `running` sem progresso: veja CPU e disco; espere antes de cancelar.
3. Cancelar: interface ou API, sem ferramenta; vira `cancelled` e o parcial é apagado.
4. `error`: leia o fim do log; ache a linha antes de `Conversion failed!`.
5. Classifique: disco, caminho/permissão, encoder, memória, mídia, timeline ou FFmpeg ausente.
6. Duração diferente: compare com o projeto; tolerância 0,5 s ou 1/fps.
7. Preto: leia `black_ranges` (medição por `blackdetect` no arquivo) antes de acusar a timeline; depois confira buracos na v1, fades e trechos sem overlay.
8. Áudio ausente: confirme se era esperado; sem fonte, sai silêncio e `audio_silent`.
9. Áudio fora da meta: compare o clipe com o render — `analyze_timeline_clip(project_id, clip_id, kind="loudness")` devolve `integrated_lufs`, `lra_lu` e `true_peak_dbfs` da fonte; `check_render_job` devolve `loudness_lufs`, `lra_lu` e `true_peak_dbfs` do arquivo. Fonte já quente (pico acima de 0 dBFS) não é bug de render; o `alimiter` fixo em 0,95 só segura o topo, e o conserto é `set_timeline_clip(volume=...)` e re-renderizar.
10. Prévia × export: 360p e CRF próprio; compare duração, fps, enquadramento e áudio, não bitrate.
11. Corrija, valide e repita em prévia; exporte após job limpo.
12. Registre job_id, projeto, erro e medições no bug.

## 5. Critérios e parâmetros
- `done` + `qc.ok: true` é sucesso; avisos podem coexistir.
- Progresso: 95 no encode, 96 na validação, 100 no fim.
- Duração: aviso acima de max(0,5 s, 1/fps); fps acima de 0,05.
- Áudio esperado e ausente: erro `audio_missing`.
- Preto: ≥0,5 s com `pix_th=0.10`; o QC devolve os intervalos medidos em `black_ranges`.
- Loudness < -60 LUFS, pico > -0,1 dBFS e sincronia > 0,15 s: avisos. Os três números de áudio (`loudness_lufs`, `lra_lu`, `true_peak_dbfs`) são medidos por `ebur128`; no material de teste o arquivo inteiro deu -4,6 LUFS, 3,0 LU e +3,9 dBFS.
- Pico só vale na janela decodificada: a análise recorta com `atrim`/`asetpts` dentro do filtro; seek de entrada (`-ss`) perde ~21 ms de priming do AAC e já devolveu 0,1 dBFS onde havia 3,9 dBFS.
- Diagnóstico lê, não edita: `analyze_timeline_clip` com `apply_candidates=true` grava marcadores (`cenas`) ou regiões (`pausas`); só use isso quando precisar mostrar os candidatos na interface, e depois `clear_timeline_annotations(project_id, group=...)` — marcadores e regiões feitos à mão ficam.
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
- [ ] Preto e loudness avaliados no contexto, com os números do render comparados aos do clipe de origem.
- [ ] Prévia aprovada antes do export.
- [ ] Evidências salvas para bug.

## 8. Validação objetiva
Sucesso: `status: done`, `qc.ok: true`, arquivo existente e não vazio. Em `measurements`, confira `duration`, `width`, `height`, `fps`, `has_audio`, `loudness_lufs`, `lra_lu`, `true_peak_dbfs`, `black_ranges` e `av_start_delta`: áudio e preto vêm dos mesmos leitores da análise por clipe (`ebur128` e `blackdetect`). Compare com `analyze_timeline_clip(kind="loudness")` no clipe suspeito antes de chamar o resultado de bug de render. QC técnico não é narrativa: ele não vê conteúdo, legenda ou intenção, e não há waveform nem curva de pico por instante. Se `black_qc_skipped` ou `loudness_qc_skipped` aparecer, a análise falhou; não é sinal de arquivo limpo.

## 9. Limitações atuais do ClipMind
Medição existe: o QC do arquivo renderizado reporta `loudness_lufs`, `lra_lu`, `true_peak_dbfs` (ebur128), `black_ranges` (blackdetect ≥ 0,5 s, `pix_th=0,10`), `av_start_delta`, duração, resolução e fps; `analyze_timeline_clip` mede o clipe da origem com os mesmos leitores — LUFS/LRA/pico, pausas (`noise`, `min_pause`) e trocas de cena (`threshold` 1–100) — e `clear_timeline_annotations` limpa o grupo que a análise gravou. Medir não corrige: não há normalização nem filtro de áudio no motor, e o único teto é o limitador fixo 0,95 (≈ -0,45 dBFS).
Não há timeout, fila persistente, retomada, checagem de disco, log completo na ferramenta, cancelamento pelas ferramentas, garantia de GPU, preview em tempo real nem QC de conteúdo: nada de transcrição, OCR de legenda, detecção de falante, waveform ou curva de pico por instante. A prévia é 360p; para reduzi-la use a API/interface com `max_height`, não a ferramenta. Alternativas: cancelar na interface, liberar disco, encurtar a timeline e repetir em prévia. Para automatizar faltariam timeouts, fila persistente, log exposto e diagnóstico de ambiente.

## 10. Ferramentas e skills relacionadas
Ferramentas: `inspect_edit_project`, `validate_timeline`, `configure_edit_project`, `render_timeline`, `check_render_job`, `analyze_timeline_clip`, `clear_timeline_annotations`, `list_editor_skills`, `load_editor_skill`. Skills: `export-and-delivery`, `timeline-debugging`, `accessibility-and-quality-control` e `multicam-editing`.
