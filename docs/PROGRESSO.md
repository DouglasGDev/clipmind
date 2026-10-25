# Progresso do editor profissional

Arquivo de acompanhamento. **Feito** = testado; **experimental** = funciona no
fluxo feliz sem suíte de testes; **planejado** = não existe.

Última atualização: 2026-10-24.

## Como verificar

```bash
python -m pytest tests -q     # suíte completa (motor, render, skills, API)
python server.py              # / (ferramentas clássicas) e /editor (timeline)
```

## Feito nesta rodada

- **Suíte HTTP da API** (`tests/test_api.py`, 83 testes): criar/listar/ativar/apagar
  projeto, cada rota de operação, undo/redo, versões, validação, render, filas,
  cancelamento, QC, mídia, uploads, skills e chat — inclusive os códigos de erro.
- **Endurecimento da camada HTTP**: corpo malformado agora devolve 400 com
  mensagem em `detail` (antes podia virar 500); `create_project` recusa campo
  inesperado em vez de ignorar; e a separação 400/404 foi corrigida — id de
  projeto, clipe ou versão que não existe é recurso ausente, o resto é pedido
  inválido. Nenhuma resposta vaza traceback.
- **Operação sem efeito não consome undo nem versão** (`_assinatura` compara o
  estado ignorando `updated_at`/`recent_operations`). Antes, repetir o mesmo
  ajuste empilhava desfazeres que não desfaziam nada.
- **Volume validado nas duas entradas** (`_valida_volume`): `add_clip` aceitava
  9 e `set_clip_properties` cortava em 4, contradizendo as docstrings que as
  ferramentas mostram ao modelo. Agora ambas rejeitam fora de 0–4.
- **Mensagens de erro legíveis**: "Clipes não encontrado" → "Clipe não
  encontrado"; a lista de cores aceitas passou a citar só os nomes em português
  (30 itens EN/PT misturados era ilegível).
- **Undo/redo validam o projeto antes de olhar a pilha**: id desconhecido cai em
  404, não em "nada para desfazer".
- **Suíte do agente da timeline** (`tests/test_timeline_agent.py`, 65 testes):
  as 19 ferramentas congeladas por nome, varredura provando que todo id
  inexistente volta como `{"ok": false}` em JSON, rejeição de colisão/velocidade/
  volume/cor sem mover nada nem gastar undo, exclusão exigindo `confirm`,
  divisão/duplicação, corte de contexto do prompt, e o LM Studio **simulado**:
  ordem dos eventos (`tool_call` → `tool_result` → `text` → `answer`), histórico
  isolado por projeto, `reset_chat`, resposta vazia, conexão recusada, token de
  autenticação mascarado, nenhum modelo baixado, descoberta de modelo e timeout
  de turno — com cliente falso, sem depender do LM Studio.
- **README** com o editor profissional: fluxo, atalhos, tabela de endpoints
  `/api/editor/*`, as 19 operações, variáveis `CLIPMIND_PROJECTS` e
  `CLIPMIND_TURN_TIMEOUT`, árvore de arquitetura e seção de testes.

Total: **641 testes em ~15 s** (`python -m pytest tests -q`), sem xfail e sem
LM Studio. Verificado também contra o servidor real: projeto `p_cfbc64a86a`
editado pela API, prévia de 6 s renderizada (640x360, 30 fps, −21,3 LUFS, true
peak −15,2 dBFS, sem preto, delta A/V 0,0) e QC aprovado.

## Rodada anterior

- Motor de timeline não destrutivo coberto por teste: conversão de tempo/fps,
  add/move/trim/split/delete/duplicate/slip/slide/roll, ripple, colisões,
  velocidade, transform/cor com limites, transição, fades, marcadores, regiões,
  `validate_project`, undo/redo transacional, persistência em disco, versões e
  restauração entre projetos (`tests/test_project_engine.py`).
- Render FFmpeg com QC medido por ffprobe/ebur128/blackdetect: prévia vs.
  exportação com mesma duração e proporção, multi-faixa com sobreposição,
  título, legenda e trilha, velocidade com `atempo` em cadeia, nomes de saída
  únicos, cancelamento removendo o parcial e erros claros sem FFmpeg
  (`tests/test_render.py`).
- Cancelamento em Windows: o processo FFmpeg é colhido (`_reapar_processo`)
  antes de apagar o parcial, com retentativas (`_apagar_arquivo`), e
  `RenderCancelled` limpa o diretório temporário mesmo disparando no meio do
  laço de progresso.
- Legendas: posição (inferior/centro/topo) validada no motor, ASS próprio com
  alinhamento determinístico e fala que excede o clipe cortada.
- Cores deixaram de ser texto livre: `normalize_color` aceita `#RRGGBB`,
  `0xRRGGBB` e nomes (PT e EN) e devolve erro claro para o resto — antes uma
  cor desconhecida virava branco em silêncio na legenda.
- Skills: 21 catálogos com as 10 seções obrigatórias em ordem, ferramentas
  conferidas contra `timeline_agent.TOOLS` e teste de catálogo/carga/busca
  (`tests/test_skills.py`).
- `editor_skills.load_skill`: o corpo truncado era calculado e descartado. Agora
  devolve o corpo truncado + frontmatter, com o flag `truncated`.
- Turno do agente com teto (`CLIPMIND_TURN_TIMEOUT`, padrão 900 s), duração
  registrada em log e exibida na interface.

## Pendente (próxima rodada)

- Fase 2 do roadmap: transcrição com timestamps e edição pelo texto, com corte
  revisável e reversível; análise de cenas e silêncio gravada no projeto.
- Validar tamanho e tipo do `POST /upload` no servidor (hoje o filtro é só o
  `accept` da interface) e listar os uploads por projeto.
- Keyframes, áudio por faixa (ducking, EQ, compressor) e LUTs — Fase 3.
- Presets de plataforma e reenquadramento 9:16 assistido — Fase 4.

## Limitações conhecidas

Ver seção 8 de `docs/ROADMAP_PROFESSIONAL_EDITOR.md` (keyframes, transições,
cor, áudio, reenquadramento, undo em memória, tempo do modelo local).
