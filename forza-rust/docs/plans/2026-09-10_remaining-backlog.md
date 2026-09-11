# Plano: pendências restantes (pós-review-refinement)

**Status: CONCLUÍDO 2026-09-10/11** — fases A–F implementadas, testadas e commitadas (gates verdes). Este documento permanece como registro do plano; comportamento atual vive nos topic docs e no código.

---

## Fase A — GUI cria o DB quando ausente (paridade Python, sem diálogo)

Python (`gui/app.py`): inspect → missing/empty/outdated → pergunta → upgrade;
unmanaged → pergunta → reset; senão bloqueia. Rust (`gui/lib.rs:149`) hoje
erra mandando rodar `db-upgrade` no CLI.

Proposta (divergência consciente, justificada): `Empty` → `upgrade()`
direto, sem diálogo — criar DB vazio nada destrói, e evita maquinaria de
diálogo Slint bloqueante antes da janela principal. `Incompatible` →
erro guiado (`maintenance db-reset`), nunca silencioso (destrutivo).
Linha de status informa "database created" no primeiro caso.
`upgrade()` já semeia o catálogo (com os 3 carros novos) — zero passo extra.

- **Arquivos:** `forza-gui/src/lib.rs` (extrair
  `ensure_database(&db_path) -> Result<DbReady>` testável: temp-missing →
  criado; current → ok; incompatible → erro), resto do `run()` inalterado.
- **Testes:** unit em `ensure_database` (3 estados) + manual (renomear DB,
  abrir GUI, confirmar criação + seed).
- **Estimativa:** 0,5 dia. **Gate:** testes + smoke manual.

## Fase B — `cars.txt` sincronizado ao confirmar carro novo

Hoje: seed vai só para `reference_cars` do DB (correto como fonte de verdade
do runtime — `known_cars()` une embarcado + DB). Lacuna: DB regenerado
redetecta os mesmos carros como novos. Python tampouco escrevia o txt.

Proposta: `decide_case`, após seed com `inserted > 0`, tenta anexar o valor
ao asset em ordem alfabética (case-insensitive, convenção do arquivo),
dedupe case-insensitive, preservando newline final. **Best-effort: nunca
falha a decisão** (DB já tem o dado; asset é conveniência para fresh DBs).
- **Resolução de caminho:** a partir de `current_exe` —
  `../../assets/cars.txt` (fonte embarcada) e `../../../cars.txt` (par
  legado); atualiza **cada um que existir**, nunca cria diretórios (não
  escreve no lugar errado). Fora do workspace (instalado) → só DB, com log.
- **Escopo:** só `car` (decide não semeia tracks; fora de escopo).
  Embarcado só vale após rebuild — documentar no código (runtime lê o DB).
- **Arquivos:** novo `forza-app/src/services/reference_assets.rs`
  (`candidate_asset_paths()`, `sync_car_to_asset(path, car) -> bool`);
  `decide_case` chama após seed; testes unit (temp file: ordenação,
  idempotência, dedupe) + integração via `decide_case` com paths injetados
  (assinatura interna com parâmetro; pública inalterada).
- **Estimativa:** 0,5–1 dia. **Gate:** testes + manual (confirmar carro novo
  → arquivo atualizado; repetir → sem duplicata).

## Fase C — Quick wins (0,5 dia, um PR)

1. **Cast `i32 as usize` (F3 original):** auditar `callbacks/` (inventory
   159/160/190/191/212–215/253/258/405/410, responses, review, debug,
   detail). Maioria já usa `.get()` (retorna `None`, sem panic) ou guarda
   `>= 0`; fechar os sem guarda com cast checado + teste de regressão
   (índice −1 nunca panica/não seleciona).
2. **Pragmas duplicadas:** extrair `fn apply_pragmas(conn)
   -> rusqlite::Result<()>` usada por `configure_connection` (map para
   `DbError`) e pelo `with_init` do pool — elimina a duplicação literal
   sem o `From` impossível (assinatura do `with_init` exige erro rusqlite).
- **Gate:** clippy/test/fmt (padrão).

## Fase D — `cli/main.rs` → `commands/` (0,5–1 dia, cosmético)

Mover `cmd_run/cmd_live_run/cmd_*` + heal helpers para
`commands/{run,rebuild,export,maintenance,heal}.rs`; `main.rs` vira
parse + dispatch. Testes existentes (`mod tests`) mudam junto, sem
mudança de comportamento. **Gate:** suite + `run --dry-run` manual.

## Fase E — Worker pool + `connection_pool` (2–3 dias)

Thread-por-request + conexão-por-request no `worker.rs`; `connection_pool`
(r2d2) órfão em prod (só teste o usa).
- **Decisão proposta:** **adotar, não remover** — pool fixo de workers
  (fila mpsc já existe) + cada job pega conexão do pool r2d2; junto o fix
  `lock().unwrap_or_else(|e| e.into_inner())` no `on_response` (poison
  hoje descarta respostas para sempre).
- **Testes:** estresse (100 filtros rápidos → respostas coerentes, sem
  freeze atrás de "loading…") + suite existente (`worker_round_trip`).
- **Gate:** stress + suite verdes.

## Fase F — Perf do hot path, com bench (2 dias+, por último)

F4 original, só com bench antes/depois + goldens inalterados, nesta ordem:
cache `Vec<(key, original)>` de tracks; `CLASS_COLORS` → `match`;
`difflib` reutilizando `Vec`/`b2j` por lote; `frontier` pré-computando
`driver_lower`/cond/temp. Sem troca de semântica de ordenação.

## Explicitamente fora

- N+1s (`lap_best_where`, `invalid_file_artifacts`) — P4, risco > ganho.
- `FlateDecode` no PDF (custo de dep por KBs).
- Tracks.txt sync (decide não semeia tracks).
- Lado Python (congelado; paridade agora é referência, não alvo).
- Mudança de semântica de ordenação/goldens.

## Ordem de execução

A → B → C → D → E → F (valor/entrega primeiro, risco depois).
Rebuild release para teste manual ao fim de cada fase.
