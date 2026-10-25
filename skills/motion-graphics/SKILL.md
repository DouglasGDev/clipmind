---
name: motion-graphics
title: Motion Graphics e Títulos
description: Títulos estáticos com posição, cor, caixa e fade, empilhados na faixa t1; sem keyframes, a animação real não existe no ClipMind.
triggers: título, cartela, texto na tela, tipografia, abertura, créditos, grafismo, lower third
tools: inspect_edit_project, add_timeline_text, set_timeline_clip, move_timeline_clip, trim_timeline_clip, split_timeline_clip, delete_timeline_clip, add_timeline_marker, validate_timeline, render_timeline, check_render_job
---

## 1. Quando usar
- Nome, cargo, local, capítulo, chamada, slogan, abertura ou créditos.
- Reforço escrito de um ponto da narração ou transição entre blocos.
- Não use para legendas de fala (`subtitles-and-captions`) nem para prometer animação real.

## 2. Objetivo
Compor gráficos tipográficos legíveis com o que existe: texto estático (drawtext) com tamanho, cor, posição e caixa controlados, entrada por `start`/`duration` e saída por fade. Empilhar clipes em `t1` cria camadas e revelações sequenciais — a única "animação" disponível.

## 3. Entradas necessárias
- Textos exatos e ordem de aparição; ortografia conferida pelo usuário.
- Instante (segundo na timeline) de cada cue e duração desejada.
- Paleta (branco, amarelo, preto ou `#RRGGBB`) e posição por destino (16:9 ou 9:16).
- Projeto já montado: o fundo define contraste e área livre.

## 4. Ferramentas disponíveis
`inspect_edit_project`, `add_timeline_text`, `set_timeline_clip`, `move_timeline_clip`, `trim_timeline_clip`, `split_timeline_clip`, `delete_timeline_clip`, `add_timeline_marker`, `validate_timeline`, `render_timeline`, `check_render_job`.

## 5. Fluxo passo a passo
1. `inspect_edit_project`: veja a faixa `t1`, colisões com títulos existentes e o que há em `s1`.
2. Marque o cue na narração com `add_timeline_marker` e combine a estética (fonte não é configurável; o render usa a padrão).
3. Uma ideia por clipe de texto, até 2 linhas; quebras manuais.
4. `add_timeline_text(text=..., start=..., duration=..., font_size=..., position=..., color=..., background=...)`.
5. Camada extra: crie segundo título em `t1` encostado ou com sobreposição em faixas diferentes de tempo; títulos na mesma faixa não podem coincidir.
6. Entrada/saída: `set_timeline_clip(fade_in=0.3, fade_out=0.3)`, entre 0,2 e 0,4 s; somas dos fades ≤ duração e permanência legível ≥ 1,5 s.
7. Ajuste fino com `move_timeline_clip` (timing) e `trim_timeline_clip(duration=...)` (tempo na tela).
8. Renderize prévia 360p e confira legibilidade, contraste, margens e colisões; valide, corrija e exporte.

## 6. Regras obrigatórias
- Nunca prometer movimento, scale, rotação animada, typewriter, trajetória ou easing: keyframes não existem.
- `background=true` sobre fundo claro ou detalhado; sem caixa, garanta contorno/contraste.
- Respeitar área segura: 5–8% das bordas; em 9:16 evitar os 15–20% inferiores (UI da plataforma).
- Título não pode cobrir legenda em `s1`; prefira `topo` ou `centro` quando houver legenda inferior.
- Só apague com `confirm=true` após aval do usuário.

## 7. Critérios de qualidade
- Título 16:9: 64–80 px; 9:16: 72–96 px; lower third 40–52 px; 2 linhas no máximo.
- Leitura estimada ≥ 1,5 s por frase e até ~18 caracteres/s.
- Fades de 0,2–0,4 s com pelo menos 1,5 s de texto pleno entre eles.
- Cores consistentes entre cartelas; sem colisão de tempo na faixa `t1`; QC final `ok=true`.

## 8. Erros comuns
- Texto longo demais para a duração, ou fonte pequena vista no celular.
- Esperar "motion graphics de verdade": a entrega é estática com fade; avise antes de começar.
- Empilhar tudo em um único `add_timeline_text` em vez de clipes separados com timing.
- Fade de 0,8 s em clipe de 2 s, engolindo a leitura.
- Esquecer que a caixa escura tem opacidade fixa e sem personalização.

## 9. Limitações do sistema atual
Não há keyframes nem animação de posição, escala, rotação, opacidade ou trajetória; fade é a única transição. Não há importação de fontes, logos, imagens, formas vetoriais, templates, partículas, tracking por caractere, pre-comp nem prévia em tempo real. Títulos são drawtext estático com posição fixa da lista (`inferior`, `topo`, `centro`, `inferior-esquerda`, `inferior-direita`). Gráficos animados reais exigem After Effects/Resolve externos; diga isso ao usuário em vez de simular com fades em série sem avisar.

## 10. Exemplo de uso
Usuário: "Cartela de abertura: título grande por 3 s e o subtítulo aparece 1 s depois, com entrada suave."
1. `add_timeline_text(text="CLIPMIND", start=0, duration=3, font_size=76, position="centro", color="white", background=false)`.
2. `add_timeline_text(text="edite com IA local", start=1, duration=2, font_size=40, position="centro", color="#FFD400", background=true)`.
3. `set_timeline_clip` em ambos com `fade_in=0.3` (e `fade_out=0.3` no segundo).
4. `validate_timeline` → `render_timeline(preview=true)` → confira e exporte. Explique que o efeito é estático com fade e que animação de letra/posição não existe hoje.
