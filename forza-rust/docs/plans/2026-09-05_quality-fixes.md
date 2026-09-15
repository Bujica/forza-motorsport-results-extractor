# Plano de correções — auditoria de qualidade 2026-09-05

**Data:** 2026-09-05
**Origem:** julgamento de procedência de `forza-rust/docs/audit-qualidade-2026-09-05.md` vs auditoria própria (67 issues compiladas de ~300 brutas, 9 crates, ~98 arquivos `.rs`).
**Decisões:** local `forza-rust/docs/plans/`; escopo agora P0+P1, P2 follow-up; MSRV 1.88+ (manter let-chains).

---

## 1. Vereditos que condicionam este plano (resumo)

### 1.1 Escopo do doc — IMPROCEDENTE (não usar como base de contagem)
- Doc diz 8 crates / 69 `.rs` / 4 com testes. Real: **9 crates**, **98 `.rs`** (77 src + 18 tests + 2 build.rs + 1 example), **8/9 com tests** (só `forza-cli` sem).
- Tabela do próprio doc lista 9 crates, contradizendo o cabeçalho.

### 1.2 Criticals do doc
| # | Item | Veredito |
|---|---|---|
| 1 | `db/external_records.rs:127` DefaultHasher | PROCEDENTE — fazer (P1-1) |
| 2 | `db/best_laps.rs:80` sentinel MAX | PARCIAL, efeito invertido (ordena por último) — rebaixar para medium |
| 3 | `db/laps.rs:155` `try_into().unwrap_or(0)` | PROCEDENTE, risco baixo — fazer (P1-1) |
| 4 | `db/laps.rs:64` `m.get(..10)` | IMPROCEDENTE; sugestão `&m[..min]` panica em boundary — NÃO fazer |
| 5 | `output/pdf.rs:1201` `/Length` | PARCIAL; sugestão `.len()` quebra (UTF-8 vs WinAnsi 1:1) — NÃO fazer |
| 6 | `gui/main.rs:13` falta `use Path` | IMPROCEDENTE, uso qualificado compila — NÃO fazer |
| 7 | `gui/ui_state.rs:50` falta `use PathBuf` | IMPROCEDENTE, `use` existe na l.7 — NÃO fazer |
| 8 | `cli/main.rs:497` `&hash[..12]` | PROCEDENTE como hardening — fazer (P1-1) |

### 1.3 Highs / strengths
- Monolitos: PROCEDENTE (medidas conferem ±1,5%).
- Error swallowing: PARCIAL (procedentes `runs.rs:630`, `cli:439`, 11× lmstudio; improcedentes `external_records.rs:80`, `ui_persist.rs:69`; parcial `cli:900`).
- Strengths confirmados: atomic `tmp+rename` (config, gui), `WAL+busy_timeout+FK` por conexão.

---

## 2. P0 — bloqueante

### P0-1. `forza-db/src/repositories/images.rs:238` — placeholders deslocados (critical)
- **Problema:** UPDATE `?2..?19` com 18 params; `?19` sem bind; `current_name` nunca NULL sobrescreve nome bom.
- **Passos:**
  1. Reindexar para `?1..` e conferir ordem param × coluna.
  2. Passar `Option` para nome/path (NULL em vez de `""`).
  3. Novo teste roundtrip com NULL + string.
- **Gate:** `cargo test -p forza-db`.

### P0-2. `forza-db/src/evidence.rs:9` — `preserve_order` quebra hash (critical)
- **Problema:** assume `Map=BTreeMap` sorted; com feature `preserve_order` vira insertion-order → hash diverge do Python.
- **Passos:**
  1. `BTreeMap` explícito ou sort-keys antes de `to_string`.
  2. Travar feature no `Cargo.toml`.
  3. Golden com chaves fora de ordem + emoji (surrogate pair).
- **Gate:** `cargo test -p forza-db evidence` + golden `request_hash`.

### P0-3. `forza-domain/src/normalizer.rs:83,147` + `car_map` Vec (critical/performance)
- **Problema:** `fix_track_name` renormaliza `refs.tracks` por chamada → O(rows·refs·nfkd); `values` clonado por chamada fuzzy; `car_map` Vec linear.
- **Passos:**
  1. Pré-computar `PreparedRef { lower, norm, key, original }` em `ReferenceData::from_lines`.
  2. `car_map: HashMap<String,String>` + getters (quebra `pub` interno).
  3. Consts `TRACK_FUZZY_CUTOFF=0.75`, `CAR_FUZZY_CUTOFF=0.85`.
  4. Bench 800 carros × 1k rows antes/depois.
- **Gate:** `cargo test -p forza-domain`, goldens track/car inalterados.

---

## 3. P1 — alta prioridade

### P1-1. Hashes e IDs
- [ ] `db/external_records.rs:127` `DefaultHasher` → `sha256` canónico.
- [ ] `forza-cli/src/main.rs:439` `unwrap_or(hash)` stale → propagar erro + log.
- [ ] `forza-cli/src/main.rs:497` slice → `get(..12).unwrap_or(hash)`.
- [ ] `db/laps.rs:155` truncamento → `saturating` ou erro (risco baixo).
- [ ] IDs `img-{nanos}` / `flg-{nanos}` → UUIDv7 ou sequência global.

### P1-2. Transações e concorrência (uma txn por item)
- [ ] `runs.rs:206` input+result; `laps.rs` `add_result`; `rebuild.rs:26` 5 passos.
- [ ] `image_rename.rs:709` DB-em-txn primeiro + rollback total.
- [ ] `migration` seed `count==0` → `INSERT OR IGNORE` incondicional + txn.
- [ ] `best_laps` N+M UPDATEs → 2 statements com `IN` chunked.
- [ ] `extraction_runner:1459` `busy_timeout 5000` + retry ou serializar writes.
- [ ] `retry_selection` sleeps 1.1s → `created_at` injetado (tira flaky).

### P1-3. `forza-lmstudio/backend.rs` + client
- [ ] Lock global durante POST → escopo só `ensure_loaded/load`.
- [ ] `reload_before_next` nunca reseta → `else { false }` + teste.
- [ ] `request_hash` sem imagem/modelo → incluir `model+prompt+image_hash`; `ascii_json_string` → `serde_json::to_string` (surrogate pairs).
- [ ] `client.rs:255` diagnóstico `[0]` → `compatible.first()`; 11× `unwrap_or_default` → erro com contexto.

### P1-4. Unificação de normalização
- [ ] `review_track_key` × `track_key` × `normalize_ascii_compare` → `text_utils::track_key` único.
- [ ] `car_match_key` vs `fix_car_name` (`Citroën` → `citro n` vs `citroen`) → uma semântica + teste.
- [ ] `weather ""` vs `"unknown"` → const única.
- [ ] `simple_best_rows` case-sensitive vs frontier insensitive → lower ambos.
- [ ] `canonical_business_key` doctor vs reviews → módulo comum + teste non-ASCII.
- [ ] `DIRTY_TRAILING` + U+2020 (†, default config) + teste `parse("1:30 †")`.
- [ ] `TCR_CARS "Ford #17Focus ST"` → conferir `assets/cars.txt` + Python.

### P1-5. Testes
- [ ] `forza-cli`: mínimo (`--limit/total`, `--debug`, `database_file()` fallback, hash curto).
- [ ] Fim dos skips silenciosos (`response_golden`, `replay_pipeline`: fixture inline sempre executada).
- [ ] `seed_demo` full-clean ou escopo basic-only travado.
- [ ] `worker_round_trip:269` assert tautológico → asserts reais; `Z:/nonexistent` → tempdir.

---

## 4. P2 — follow-up
- [ ] Dedups: `lazy_regex!`, `api_base`, `fmt_float`, `civil_from_days`, `path_key`, `safe_name`, `PROCESSING_PROJECTION`.
- [ ] `gui/lib.rs` god-file: extrair `db_resolve`/geometria/callbacks; CSV/PDF para worker; pool vs thread-por-request; guarda `i32→usize`; clipboard `cfg(windows)`.
- [ ] `config`: warning em `read_ini` ilegível; `strict` falha em unknown-keys; `00`→None; validar arquivo atual com changes vazio.

## 5. NÃO fazer
- P0 imports GUI; fix `pdf.ops.len()`; fix `&m[..min]`; contagens/scorecards do doc.

## 6. Ordem de execução
1. P0-1 → P0-2 → P0-3 (1 PR, teste por item).
2. P1-1 → P1-5 (1–2 PRs por tema).
3. Gate final: `cargo test --workspace` + `cargo clippy -- -D warnings`.
