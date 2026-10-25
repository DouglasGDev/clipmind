---
name: color-grading
title: Color grading e look
description: Cria um look criativo com eq, mantém consistência entre planos e preserva a faixa legal sem LUT.
triggers: color grading, grading, look, estilo de cor, tonalidade, saturação criativa, contraste, gamma, consistência de cor, visual
tools: inspect_edit_project, add_timeline_clip, set_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job, list_editor_skills, load_editor_skill
---

## 1. Objetivo
Aplicar um look criativo e consistente com o `eq` por clipe, depois da correção. O motor oferece brilho, contraste, saturação e gamma; não oferece matiz, LUT ou emulação de filme. Trabalhe em passos pequenos e valide na prévia.

## 2. Quando usar
- Depois que exposição, contraste e pele já estão neutros (`color-correction`).
- Quando o projeto precisa de identidade visual consistente.
Não use para corrigir exposição/dominante nem espere LUT, curvas ou split tone.

## 3. Diagnóstico antes de editar
1. `inspect_edit_project`: confirme os valores existentes e se a correção já foi aplicada. Não empilhe grading sobre dominante.
2. Gere prévia e avalie contraste, saturação, pele, pretos, altas luzes e planos com luz diferente.
3. Escolha um plano herói e separe os planos por cena/luz; o look é decidido por cena, não por clipe isolado.
4. Cheque a faixa legal (8 bits: 16–235) e a pele. Sem scopes, o julgamento é visual e conservador.

## 4. Procedimento
1. Marque o herói ("look ref") e gere a prévia de referência.
2. Defina o look em palavras e traduza para números: contraste 1,05–1,25, saturação 0,85–1,2, gamma 0,95–1,08.
3. Aplique no herói com `set_timeline_clip`: um campo por vez, passos de 0,02–0,05.
4. Use `contrast` para pretos/brancos, `gamma` para médios e `saturation` para intensidade. `brightness` só compensa ±0,03.
5. Copie os valores para a mesma cena e ajuste só ±0,02 para diferenças de exposição. Não invente um look por clipe.
6. Confira pele, pretos e altas luzes no corte; saturação acima de 1,2 deve ser reduzida. Renderize, valide, exporte e registre em marcador.

## 5. Critérios e parâmetros
| Campo | Faixa de grading | Risco |
| --- | --- | --- |
| `contrast` | 1,05–1,25 | >1,3 esmaga sombras |
| `saturation` | 0,85–1,2 | >1,2 pele artificial |
| `gamma` | 0,95–1,08 | Médios lavados/pesados |
| `brightness` | -0,03 a 0,03 | Compensação, não look |

Receitas iniciais (contraste/saturação/gamma), confirme na prévia:
- Natural 1,05/1,05/1,0; contraste 1,15/1,0/0,98.
- Vívido 1,18/1,15/1,0 (pele é o limite); dessaturado 1,08/0,85/1,02.

Looks discretos de `eq`, não emulação. Mantenha 16–235 e a mesma receita na cena.

## 6. Erros comuns
- Grading antes da correção amplifica dominante/exposição errada.
- Exagerar saturação/contraste: pele laranja, pretos sem detalhe, banding.
- Aplicar valores diferentes em cada clipe e quebrar a continuidade.
- Usar `brightness` como look e estourar altas luzes.
- Prometer teal-and-orange, LUT ou "film look": não há controle de matiz.

## 7. Checklist de qualidade
- [ ] Correção concluída antes do look.
- [ ] Look definido e registrado em marcador.
- [ ] Pele natural e saturação ≤ 1,2.
- [ ] Pretos e altas luzes com detalhe.
- [ ] Planos da mesma cena com o mesmo look.
- [ ] Prévia e QC final aprovados.

## 8. Validação objetiva
1. `validate_timeline` com `ok=true` e nenhum erro.
2. `check_render_job` com `status=done` e `qc.ok=true`; leia os avisos.
3. `inspect_edit_project` confirma a mesma receita na cena e valores nas faixas.
4. `black_ranges` sem preto não intencional; o QC não mede saturação nem altas luzes.
5. Compare prévia e arquivo final; peça revisão humana e exporte só após aprovar a prévia.

## 9. Limitações atuais do ClipMind
- Não há LUT (`.cube`), curvas, color wheels, HSL, máscaras ou correção secundária; o look é global por clipe (brilho, contraste, saturação, gamma).
- Sem temperatura, tinta, split tone ou matiz; teal-and-orange e emulação não são possíveis.
- Não há scopes, gestão de cor, HDR, grão, halation ou keyframes.
- LUT/curvas exigiriam `lut3d`/`curves` em FFmpeg e mudança de código; processar fora não atualiza o projeto.

## 10. Ferramentas e skills relacionadas
- Ajuste: `inspect_edit_project`, `set_timeline_clip`, `add_timeline_marker`.
- Validação e entrega: `validate_timeline`, `render_timeline`, `check_render_job`.
- Catálogo e afins: `list_editor_skills`, `load_editor_skill`; `color-correction` (antes), `motion-graphics`, `subtitles-and-captions`.
