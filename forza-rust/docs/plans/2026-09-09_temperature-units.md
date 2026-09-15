# Temperatura independente da unidade do jogo (SI vs imperial) — problema e proposta

**Data:** 2026-09-09
**Status:** registrado, NÃO implementado (decisão do autor em 2026-09-09).
**Relacionados:** `2026-09-05_quality-fixes.md`, `2026-09-06_quality-followups.md`,
commit `520027b` (gate de janela), commit `72e38d6` (heal de janela).

---

## 1. Problema

O pipeline assume que `tf` (temperatura lida pelo modelo) está sempre em °F:

- Prompt (`forza-rust/assets/prompt_user_header_shaped_v1.txt:5`,
  `forza/prompts.py:15`): `tf: Track Temperature (°F)` — sem menção a unidades.
- Parse/validação (`response.rs`, `model_response.py`, `json_repair`) nunca
  tocam em `tf`; conversão (`lap.rs:192`, `domain/lap.py:144`) valida contra
  a janela `[temp_min_f, temp_max_f]` (default 40–140).
- Nenhuma chave de config de unidade existe (`temperature_unit`,
  `game_units`, etc. — grep só acha `fahrenheit_to_celsius` e a janela).

Mas o HUD do jogo respeita a configuração do jogo/console: métrico (°C) ou
imperial (°F). Evidência observada em 2026-09-09 (37 voltas, 5 imagens,
todas `Race 001`/únicas da sessão):

| tf lido | Imagem |
|---|---|
| 18 | Michelin Raceway Road Atlanta Short Course - D - Race 001.png |
| 23 | Sebring International Raceway Full Circuit - C - Race 001.png |
| 26 | Sebring International Raceway Short Circuit - A.png |
| 24 | Watkins Glen International Speedway Full Circuit - C - Race 001.png |
| 0 | WeatherTech Raceway Laguna Seca Full Circuit - C - Race 001.png |

As 7 imagens mais antigas estavam com o jogo em SI; na mais antiga a
temperatura sequer aparecia no HUD (daí o `tf=0`).

Consequências por caso:

- Valor métrico fora de 40–140 (ex. `21°C` lido como `21`): anulado pela
  janela — perda de dado, mas direção segura.
- Valor métrico DENTRO de 40–140 (ex. `60°C` lido como `60`): persistido
  como `60°F/15.6°C` — **corrupção silenciosa** (fator ~2×), que ainda
  contamina o frontier via `temp_key`.
- `tf=0` (HUD sem temperatura): NULL pela janela — resultado correto pelo
  motivo errado; registrado aqui para não confundir com as linhas acima.

Mitigação já aplicada (não resolve a causa): gate de inserção + heal
`db-heal → laps.out_of_window_temp`.

## 2. Insight de leitura

O sufixo `°C/°F` é minúsculo e o modelo já demonstrou copiar só dígitos.
Porém a imagem contém o campo **track length em KM ou MI**, maior e de
fácil visualização — sinal confiável do sistema de unidades do HUD.

## 3. Proposta aprovada (não implementada)

**Só o prompt muda; nenhum schema, nenhum código de parse, nenhum campo
novo.** `tf` continua "temperatura em °F, inteiro" em todos os schemas
(prompt, validação, banco, CSV).

1. **Prompt** (Rust + Python, paridade byte-a-byte): instrução junto ao
   campo `tf` — o HUD pode ser métrico (°C, comprimento em KM) ou imperial
   (°F, MI); usar a unidade do track length para decidir; sempre retornar
   `tf` em °F inteiro, convertendo se preciso.
2. **Goldens**: `snapshot_id`/hash do prompt muda (versionado por desenho) —
   atualizar teste de identidade Rust + espelho Python.
3. **Teste estático leve**: assert de que o texto do prompt menciona KM/MI
   e °F (anti-regressão da instrução).
4. **Limitação**: linhas antigas com temp anulado não são recuperáveis
   (unidade passada desconhecida) — correto deixar NULL.

## 4. Riscos assumidos

- Conversão mental do modelo (21 °C → 70 em vez de 69.8): erro ≤ 1 °F,
  irrelevante para o frontier; janela continua como rede contra erros
  grosseiros.
- Modelo que ignorar a instrução: recai no status quo atual (janela anula
  ou, no pior caso, valor plausível-errado) — sem regressão.

## 5. Alternativas descartadas (com motivo)

- **Chave de config `temperature_unit`**: exige que o usuário saiba/declare;
  biblioteca mista (troca no meio) não resolve por imagem.
- **Auto-detect via `tu` (unidade da temperatura)**: depende do glifo
  minúsculo — o elo fraco original.
- **Auto-detect via `tl`+`tlu` (valor+unidade do track length)**: duas
  fontes que podem discordar; autor dispensou persistir `tl`.
- **Heurística por valor** (ex. < 40 → °C): zona de sobreposição ambígua
  (72); conversão silenciosa errada. Rejeitada.
