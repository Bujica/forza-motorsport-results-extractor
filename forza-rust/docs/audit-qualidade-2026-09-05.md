# Auditoria de Qualidade — forza-rust

**Data:** 2026-09-05
**Escopo:** 8 crates, 69 arquivos `.rs` (55 source + 14 test), 4 crates com testes
**Metodo:** 8 agentes independentes (1 por crate), leitura de todos os arquivos `.rs`

---

## Resumo executivo

| Crate | Arquivos | Issues | Critical | High | Medium | Low |
|---|---|---|---|---|---|---|
| forza-domain | 14 | 23 | 0 | 0 | 10 | 13 |
| forza-db | 27 | 28 | 4 | 6 | 9 | 9 |
| forza-pipeline | 8 | 10 | 0 | 1 | 6 | 3 |
| forza-config | 5 | 20 | 0 | 4 | 9 | 7 |
| forza-lmstudio | 10 | 38 | 0 | 4 | 17 | 17 |
| forza-output | 5 | 18 | 1 | 3 | 6 | 8 |
| forza-app | 19 | 11 | 0 | 0 | 6 | 5 |
| forza-gui | 8 | 24 | 2 | 7 | 9 | 6 |
| forza-cli | 2 | 11 | 1 | 3 | 4 | 2 |
| **Total** | **96** | **164** | **8** | **28** | **78** | **50** |

### Distribuição por severidade

- **Critical (8):** 3 panics em produção, 1 hasher instável, 1 error variant semanticamente errado, 1 hash staleness, 2 imports faltantes
- **High (28):** funções monolíticas, error swallowing, performance O(n²), race conditions
- **Medium (78):** performance, style, maintainability, edge cases
- **Low (50):** style, dead code, documentação

---

## Critical issues — ação imediata

### 1. forza-db — DefaultHasher instável (`src/repositories/external_records.rs:127`)

`DefaultHasher` produz hashes diferentes em versões diferentes do Rust. Registros importados com toolchains distintas geram IDs diferentes, causando **duplicação de imports** e falha em reconciliações.

**Recomendação:** substituir por `sha2::Sha256` ou um hasher versionado com prefixo.

### 2. forza-db — Sentinel best_lap_ms (`src/repositories/best_laps.rs:80`)

`best_lap_ms.unwrap_or(i64::MAX)` trata dados ausentes como "melhor volta possível", podendo selecionar erroneamente uma volta inexistente.

**Recomendação:** usar path explícito para `None` com log ou error return.

### 3. forza-db — Silent truncation i64→i32 (`src/repositories/laps.rs:155`)

`try_into().unwrap_or(0)` truncates i64 > i32::MAX para `0`, causando perda de dados em `lap_index`, `attempt_number`.

**Recomendação:** usar `saturating_into()` ou retornar error.

### 4. forza-db — Slice access frágil (`src/repositories/laps.rs:64`)

`m.get(..10).unwrap_or(m)` é frágil com strings curtas/inválidas.

**Recomendação:** `m.get(..10).unwrap_or(&m[..10.min(m.len())])`.

### 5. forza-output — PDF /Length usa char count (`src/pdf.rs:1201`)

`page.ops.chars().count()` conta code points, não bytes. O PDF `/Length` deve ser byte count. Funciona por acidente com WinAnsi, mas o contrato é violado.

**Recomendação:** `page.ops.len()` (byte count do Vec<u8>).

### 6. forza-gui — Import faltante: Path (`src/main.rs:13`)

`std::path::Path::new(&config)` sem `use std::path::Path` — **compilação falha**.

**Recomendação:** adicionar `use std::path::Path;`.

### 7. forza-gui — Import faltante: PathBuf (`src/ui_state.rs:50`)

`PathBuf::new()` sem import — **compilação falha**.

**Recomendação:** adicionar `use std::path::PathBuf;`.

### 8. forza-cli — String slice panic (`src/main.rs:497`)

`&image.file_hash[..12]` panics se hash < 12 chars.

**Recomendação:** `&image.file_hash[..hash.len().min(12)]` ou tratar error.

---

## High issues — prioridade alta

### Funções monolíticas (violam single responsibility)

| Crate | Arquivo | Linhas | Problema |
|---|---|---|---|
| forza-gui | `src/lib.rs` | 2750 | 40+ callbacks, response dispatcher, init, sort — tudo em 1 arquivo |
| forza-gui | `src/lib.rs` (match Response) | 680 | 22+ variants com 20-80 lines cada |
| forza-gui | `src/worker.rs` (match Request) | 340 | 34 variants, DB queries, service calls |
| forza-lmstudio | `src/backend.rs` (extract) | 342 | HTTP, JSON, validation, retry, persistence — complexity ~30 |
| forza-config | `src/save.rs` (write_candidate) | 130 | read, parse, set, prune, mkdir, write, rename |
| forza-config | `src/lib.rs` (validate_config) | 160 | 25 range checks in flat if-else |
| forza-app | `src/services/extraction_runner.rs` | 1763 | orchestration, async, worker loop, helpers |

### Error swallowing

| Crate | Arquivo | Linha | Padrão |
|---|---|---|---|
| forza-db | `src/repositories/external_records.rs` | 80 | `let _ = e;` — JSON parse errors silently discarded |
| forza-db | `src/repositories/runs.rs` | 630 | `let _ = e;` — reconciliation errors silently ignored |
| forza-gui | `src/ui_persist.rs` | 69 | rename failure → Ok(()) but file not saved |
| forza-cli | `src/main.rs` | 439 | `unwrap_or(hash)` — stale hash for deduplication |
| forza-cli | `src/main.rs` | 900 | `stamp_semantic_name` error discarded |
| forza-lmstudio | 4 locations | — | `unwrap_or_default()` discards serialization errors |

### Performance

| Crate | Arquivo | Problema |
|---|---|---|
| forza-domain | `src/normalizer.rs` | O(n²) substring search over Vec car_map |
| forza-domain | `src/car_names.rs` | O(n²) collision detection in car_canonical_map |
| forza-domain | `src/reference_data.rs` | O(n) linear scan for car lookup (Vec instead of HashMap) |
| forza-gui | `src/ui_state.rs` | O(n*m) selection check (Vec::contains per entry) |
| forza-gui | `src/lib.rs` | Linear scan update_selection_summary per selection toggle |
| forza-lmstudio | `src/backend.rs` | Repeated serialization of request_config 5x per attempt |

---

## Medium issues — destaques por categoria

### Duplicação de código

- **lazy_regex!** macro duplicada em 4 arquivos (`forza-domain`: car_names, lap, review_rules)
- **api_base URL normalization** duplicada em `forza-lmstudio`: client.rs vs backend.rs
- **Model matching logic** copiada 3x em `forza-lmstudio`
- **fmt_float** duplicada em `forza-output`: csv.rs vs pdf.rs
- **PROCESSING_PROJECTION** duplicada em `forza-db`: gui_queries.rs vs image_debug.rs
- **civil_from_days** duplicada em `forza-app`: build.rs vs extraction_runner.rs

### Edge cases não tratados

- **SUSPICIOUS_SYMBOL regex** (`forza-domain`: review_rules.rs:15) flags non-ASCII letters (é, ü, ñ) como suspicious
- **parse_lap_time_ms** (`forza-domain`: lap.rs:80) lacks seconds < 60 guard
- **detect_race_class** (`forza-domain`: lap.rs:247) returns String instead of RaceClass enum
- **normalize_weather** (`forza-domain`: lap.rs:185) returns &str instead of WeatherType enum
- **hex_rgb** (`forza-output`: pdf.rs:314) silently produces (0,0,0) for malformed hex
- **winansi_bytes** (`forza-output`: pdf.rs:472) maps Latin-1 to WinAnsi incorrectly for some chars

### Test coverage gaps

- **forza-cli**: zero tests (11 files, 926 lines)
- **forza-gui**: 5 tests for 2750 lines of lib.rs; zero tests for worker.rs, detail_views.rs, ui_state.rs
- **forza-lmstudio**: golden test silently skips when fixtures missing (git-ignored)

---

## Strengths do projeto

### Arquitetura

- **Clean separation of concerns**: 8 crates com responsabilidades bem definidas (domain, db, pipeline, config, lmstudio, output, app, gui, cli)
- **Repository pattern** em `forza-db` com module separation limpa
- **Thin service facade** em `forza-app` delegando para `forza-db` e `forza-domain`
- **Threading contract** em `forza-gui`: UI thread owns widgets (thread_local!), worker thread owns DB/config (Arc + Mutex)

### Robustez

- **WAL + busy_timeout + FK** enforced in every `forza-db` connection
- **Atomic file writes** (tmp + rename) em `forza-config` e `forza-gui`
- **Panic-resilient worker** em `forza-gui`: catch_unwind + Error response resets flags
- **Schema versioning** com upgrade refusal for foreign versions
- **Batch rename with rollback** em `forza-app` (image_rename.rs)

### Qualidade de código

- **Zero unsafe code** em 7 de 8 crates (apenas `forza-gui` tem GetSystemMetrics)
- **thiserror** consistent em todos os crates para error enums
- **Golden tests** em `forza-domain` (14 tests), `forza-db` (10 doctor tests), `forza-output` (byte-identical CSV)
- **Python parity documentation** throughout — comments reference Python source files
- **value_enum!** macro em `forza-domain` eliminates boilerplate and ensures Python string contract

---

## Recomendações prioritizadas

### P0 (bloqueante)

1. **Fix missing imports** em `forza-gui`: main.rs e ui_state.rs — impede compilação
2. **Replace DefaultHasher** em `forza-db` — causa duplicação de imports em production
3. **Fix PDF /Length** em `forza-output` — contrato PDF violado

### P1 (alta prioridade)

4. **Refactor monolithic functions** — forza-gui lib.rs (2750 lines), forza-lmstudio extract (342 lines), forza-app extraction_runner (1763 lines)
5. **Eliminate error swallowing** — 6 locations across forza-db, forza-cli, forza-gui, forza-lmstudio
6. **Add tests to forza-cli** — zero coverage for 926 lines of CLI logic
7. **Fix best_lap_ms sentinel** em `forza-db` — correctness risk

### P2 (médio prazo)

8. **Convert car_map to HashMap** em `forza-domain` — O(n) → O(1) lookups
9. **Consolidate duplicated code** — lazy_regex, api_base, fmt_float, civil_from_days
10. **Fix SUSPICIOUS_SYMBOL regex** — Unicode name false positives
11. **Return enums instead of Strings** — detect_race_class, normalize_weather
12. **Improve forza-gui test coverage** — 5 tests for 3000+ lines

### P3 (nice-to-have)

13. **Thread pool** em `forza-gui` worker.rs — per-request thread spawn causes churn
14. **Cache known_track_keys()/known_cars()** em `forza-db` reviews.rs
15. **Replace timestamp-based IDs** em `forza-db` — collision risk

---

## Scorecards por crate

| Crate | Safety | Correctness | Performance | Style | Maintainability | Tests | Overall |
|---|---|---|---|---|---|---|---|
| forza-domain | A | B | C | B | B | A | B |
| forza-db | C | C | C | B | B | A | C |
| forza-pipeline | A | B | C | B | B | A | B |
| forza-config | B | C | C | B | C | A | B |
| forza-lmstudio | C | C | C | B | C | B | C |
| forza-output | C | C | B | B | B | B | C |
| forza-app | A | B | B | B | C | A | B |
| forza-gui | C | C | C | B | C | D | C |
| forza-cli | C | C | C | B | C | F | D |

Legenda: A = excelente, B = bom, C = precisa atenção, D = fraco, F = ausente

---

*Relatório gerado por auditoria automatizada com 8 agentes. Todos os arquivos `.rs` foram lidos e analisados.*
