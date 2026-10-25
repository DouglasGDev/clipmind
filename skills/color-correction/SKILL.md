---
name: color-correction
title: Correção de cor
description: Neutraliza exposição, contraste e saturação, aproxima o balanço de branco e iguala planos antes do grading.
triggers: correção de cor, exposição, balanço de branco, saturação, contraste, pele, igualar planos, clarear, escurecer, dominante
tools: inspect_edit_project, add_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, list_editor_skills, load_editor_skill
---

## 1. Objetivo
Neutralizar exposição, contraste, saturação e dominantes no possível, plano a plano, antes do look. Alvo: consistência e pele natural. Use `eq` por clipe em passos pequenos e confirme na prévia; não é grading.

## 2. Quando usar
- Material escuro, estourado, sem contraste, com planos desiguais ou pele alterada.
- Antes do grading. Não use para look, LUT ou log.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: leia `brightness`, `contrast`, `saturation`, `gamma` de cada clipe e a ordem dos planos.
2. Prévia (`preview=true`): altas luzes, sombras e brilho geral.
3. Avalie dominantes e pele (verde, magenta, azul, amarelo); não há temperatura/tinta nem scopes.
4. Compare planos vizinhos no corte, identifique luz mista e escolha um plano de referência.
5. Não invente perfil de câmera ou espaço de cor; material log/flat terá correção limitada sem LUT.

## 4. Procedimento
1. Prévia de referência; marque o plano herói com `add_timeline_marker` ("cor ref").
2. Neutralize o herói (`brightness=0`, `contrast=1`, `saturation=1`, `gamma=1`) e aplique um campo por vez.
3. Exposição: `brightness` em passos de 0,02–0,05, no máximo ±0,1; para médios use `gamma` (0,95–1,08); contraste em 0,95–1,10.
4. Saturação por último: 0,95–1,05; não passe de 1,1 com pele. Balanço de branco não existe: saturação 0,95–1,0 apenas atenua dominante leve; matiz forte é limitação.
5. Iguale os vizinhos copiando o herói e ajustando ±0,02–0,03; renderize, valide, exporte e registre em marcador.

## 5. Critérios e parâmetros
| Campo | Padrão | Faixa segura | Efeito |
| --- | --- | --- | --- |
| `brightness` | 0 | -0,1 a 0,1 | Sobe/baixa tudo; clipa fácil |
| `contrast` | 1 | 0,9–1,15 | Separa pretos e brancos |
| `saturation` | 1 | 0,9–1,1 | Cor global; pele satura antes |
| `gamma` | 1 | 0,9–1,08 | Médios; >1 clareia, <1 escurece |

- Ordem do motor: `brightness` → `contrast` → `saturation` → `gamma`.
- Faixa legal em 8 bits: 16–235; sem scopes, evite os extremos.

## 6. Erros comuns
- Corrigir tudo de uma vez e usar saturação para resolver balanço de branco: a dominante continua.
- Subir `brightness` para salvar subexposição: revela ruído e banding.
- Aumentar contraste antes de acertar exposição e esmagar sombras.
- Copiar valores entre planos de luz diferente sem reavaliar, ignorar a pele ou fazer grading antes da correção.
- Afirmar medição de scopes ou temperatura: não existem no ClipMind.

## 7. Checklist de qualidade
- [ ] Exposição e contraste sem extremos.
- [ ] Branco neutro e pele natural.
- [ ] Saturação ≤ 1,1 em planos com pele.
- [ ] Planos vizinhos com o mesmo tom e brilho.
- [ ] Nenhuma dominante forte apresentada como corrigida.
- [ ] Prévia aprovada, valores registrados e QC final conferido.

## 8. Validação objetiva
1. `validate_timeline` com `ok=true` e nenhum erro.
2. `check_render_job` com `status=done` e `qc.ok=true`; leia os avisos.
3. `black_ranges` sem trechos não intencionais; o QC pega preto ≥ 0,5 s, não sombra esmagada.
4. `inspect_edit_project` confirma valores dentro das faixas e consistentes entre planos.
5. Compare prévia e arquivo final e peça revisão humana; o QC não mede cor, então exporte após a prévia aprovada.

## 9. Limitações atuais do ClipMind
- Não há temperatura, tinta ou balanço de branco real; o `eq` não corrige matiz. Exigiria `colorbalance`/`colortemperature` em FFmpeg e mudança de código.
- Não há LUT, curvas, HSL, máscaras, correção secundária nem ajuste por área.
- Não há scopes, medição de pele/exposição, gestão de cor, HDR, log, keyframes ou camadas de ajuste.
- `eq` é por clipe, com ordem fixa; processar externamente não atualiza o projeto.

## 10. Ferramentas e skills relacionadas
- Ajuste: `inspect_edit_project`, `set_timeline_clip`, `add_timeline_marker`.
- Validação e entrega: `validate_timeline`, `render_timeline`, `check_render_job`.
- Catálogo e afins: `list_editor_skills`, `load_editor_skill`; `color-grading`, `audio-post-production`, `motion-graphics`.
