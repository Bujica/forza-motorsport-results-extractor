# Plano follow-up — pendências da auditoria de qualidade 2026-09-05

**Data:** 2026-09-06
**Origem:** itens previstos em `2026-09-05_quality-fixes.md` e não executados,
mais medium/low da auditoria triados como futuros. Nada aqui é bloqueante:
P0 + P1 + P2-dedups estão implementados (commits `324e6c3`→`1b5d83f`),
com `fmt --check` + `clippy -D warnings` + `cargo test --workspace` verdes
e hook pre-push instalado (`.githooks/pre-push`).

Convenção: cada item traz **motivação**, **escopo concreto** e **gate**.
Itens marcados ⛔ foram julgados improcedentes/paridade — NÃO fazer.

---

## F1. GUI: quebrar o god-file `gui/lib.rs` (~2710 linhas)

- **Motivação:** `run()` + 40 callbacks + dispatcher + sorts com allocs por
  comparação; qualquer mudança na UI atravessa um arquivo só.
- **Escopo:**
  1. Extrair `db_resolve` (fallback CWD/exe/ini + heurística "maior vence")
     para `gui/src/db_resolve.rs` com testes (resolver relativo ao ini).
  2. Extrair geometria/tipos de callback para módulos.
  3. `sort_by_cached_key` + `HashSet` em `update_selection_summary`.
  4. Mover CSV/PDF (`bestlaps_export_csv`, `generate_pdf`) para
     `Request::ExportCsv/GeneratePdf` no worker com progresso.
- **Gate:** comportamento idêntico (testes `worker_round_trip` + manuais GUI),
  clippy/test verdes.

## F2. Worker: pool em vez de thread-por-request (`gui/worker.rs:892`)

- **Motivação:** digitação em filtro = N threads; `Mutex` poisonado descarta
  respostas para sempre; respostas fora de ordem (o teste P1-5 precisou de
  2 fases por isso).
- **Escopo:** pool fixo (ou `rayon`/canal com N workers) + coalescer filtros;
  `lock().unwrap_or_else(|e| e.into_inner())` no `on_response`.
- **Gate:** teste de estresse (100 filtros rápidos → respostas coerentes),
  suite verde.

## F3. Seleção com cast `i32 → usize` (`gui/lib.rs:1496`)

- **Motivação:** `end as usize` com `-1` vira `usize::MAX` (panic debug /
  seleção esvaziada release).
- **Escopo:** validar `index >= 0` antes de anchor/range + teste unitário.
- **Gate:** teste de regressão, clippy.

## F4. Performance fina do hot path (medir antes)

- **Motivação:** `fix_*` ainda faz fuzzy O(refs) por chamada; `frontier`
  clona ~7 Strings/row; `difflib::ratio` aloca `Vec<char>`+`HashMap` por
  comparação; `CLASS_COLORS` paga SipHash por lookup; `track_suggestions`
  renormaliza candidatos.
- **Escopo (nesta ordem, com bench):**
  1. Cachear `Vec<(key, original)>` de tracks para sugestões (`LazyLock`).
  2. `CLASS_COLORS` → `match` (12 entradas fixas).
  3. `difflib`: reutilizar `Vec`/`b2j` por lote em vez de por comparação.
  4. `frontier`: pré-computar `driver_lower`/`cond`/`temp` uma vez por chamada.
- **Gate:** bench antes/depois + goldens inalterados. NÃO trocar semântica
  de ordenação (goldens Python).

## F5. Qualidade transversal

- **Lints por crate:** `#![deny(unsafe_code)]` onde já é verdade (7/9 crates),
  `#![warn(missing_docs)]` em `domain`/`pipeline`; unificar `thiserror`
  (domain manual, app/gui/cli `anyhow`/`String`).
- **Escopos menores:** `update_run_metadata` e `UPDATE`s sem checar
  `changes()==1`; `workers` em `[llm]` vs resto em `[lmstudio]` (documentar
  ou migrar com teste); `table_count` com `format!` (allowlist já que é
  privado, mas padronizar `quote_identifier`).
- **Testes menores:** `pdf_render` sleep 1.1s → relógio injetável;
  `schema_lifecycle` comparar `user_version`+dump em vez de tamanho;
  `retry_selection` trocar sleeps por `created_at` injetado.
- **Gate:** clippy/test verdes por item.

## F6. Reavaliar sob mudança de contrato (fazer só com migração)

- `strict` falhar em unknown-keys (hoje warning-only; quebraria configs
  legadas com chaves allow-listadas).
- `normalize_weather`/`detect_race_class` retornarem enums em vez de `&str`/
  `String` (exige mudança conjunta Python+Rust).
- `simple_best_rows` case-insensitive e `ordering` `""`→`"unknown"` (idem —
  Python usa chave exata e `""`; ver `frontier.py:30`).

## ⛔ NÃO fazer (vereditos registrados)

- PDF `/Length` → `.len()` (quebraria: UTF-8 vs WinAnsi 1:1).
- `laps.rs:64` → `&m[..min]` (panica em boundary; atual nunca panica).
- "Imports faltantes" GUI, contagens do doc (69 vs 98 arquivos reais).
- TCR `"Ford #17Focus ST"`: catálogo + Python idênticos, não typo.

---

## Ordem sugerida

F3 (pequeno, safety) → F1+F2 (GUI, juntos) → F4 (com bench) → F5 (fatia por
fatia) → F6 (só sob RFC de contrato).
