# Plano de execução — dedup runner/discovery, doctor, GUI, encoding

**Data:** 2026-09-10
**Origem:** auditoria rodada set/2026 (extraction_runner, doctor, gui/lib.rs, cli/main.rs, pdf.rs, backend.rs, encoding.rs, review_queue, repositórios, evidence/migration/json_repair).
**Baseline:** `cargo test --workspace` verde, 0 falhas (2026-09-10).
**Convenção:** cada fase tem escopo, arquivos, testes e gate. P3/P4 são observações — não agendar.

---

## Fase 1 — `encoding.rs`: decode redundante (P1, 30 min, risco ~zero) ✅ próximo

- **Arquivo:** `crates/forza-pipeline/src/encoding.rs:127-140`
- **Mudança:** trocar re-decode de `bytes` por `(dynamic.width(), dynamic.height())`.
  `dynamic` já tem a dimensão pós-`resize_exact`; encoders não alteram dimensão.
- **Teste novo:** encode PNG+JPEG de fixture, assert dimensão pós-`max_width` + `byte_count`.
- **Gate:** `cargo test -p forza-pipeline && cargo clippy -p forza-pipeline`.

## Fase 2 — Discovery único (P1, 1–2 dias, risco médio)

- **Problema:** 3 cópias da montagem do plano — `cli/main.rs:439-476` (dry-run+`println!`),
  `extraction_runner.rs:418-478` (`on_event(Plan)` + `selected_image_file_ids`).
  Divergência já materializada: re-hash falho → CLI `SKIP` ruidoso vs. runner `unwrap_or(hash)` stale.
- **Alvo:** novo `forza-app/src/services/discovery_plan.rs` com
  `build_discovery_plan(DiscoveryInput) -> Result<DiscoveryOutput, String>`,
  política única (nunca planejar sob hash stale), log via callback
  (`eprintln!` no CLI, `on_event(Log)` no runner).
- **Passos:** criar módulo → reescrever `cmd_run` → reescrever `run_async` →
  testes (retry vazio/faltando, force+retry=erro, limit, selected_ids, re-hash falho=skip).
- **Gate:** CLI dry-run e `RunEvent::Plan` com mesmos números na mesma fixture;
  `grep unwrap_or(hash)` no runner retorna 0; `cargo test -p forza-app -p forza-cli`.

## Fase 3 — Estágios de rede do runner, por partes (P1, 2–4 dias)

Não fazer big-bang `process_one_image`. Ordem:
1. **3.a** `fail_result()` + `emit_progress()` — unifica os ~10 blocos `UPDATE status='error'`.
2. **3.b** `finalize_ok_stage()` — `finalize_result_ok` + `UPDATE request_image_*` +
   `stamp_semantic_name` num só lugar (bug do stamping vira impossível).
3. **3.c** `encode_stage` + `ensure_loaded_stage`.
4. Só então avaliar `process_one_image` com trait `Emitter`. Se 3.a–3.c zerarem a
   divergência, parar aqui.
- **Gate:** 1 local por tipo de erro + 1 local que carimba `semantic_name`;
  run ao vivo curto com mesmos resultados; `cargo test -p forza-app`.

## Fase 4 — Split `doctor.rs` (P2, 1 dia, risco baixo)

- Fronteiras: `sqlite/status/run/image_file/review/artifact/schema_checks`
  (comentários `// ── X (y_checks.py) ──` já existentes).
- Criar `forza-db/src/doctor/{mod,sqlite,status,run,image_file,review,artifact,schema,types}.rs`;
  `mod.rs` reexporta `DoctorCheck/Report/run_doctor`. Sem mudar SQL/severidade/nomes.
- **NÃO fazer:** helper genérico de parent-mismatch (SQLs diferem, `check_sql` já basta),
  nem reescrever N+1 `invalid_file_artifacts` (volume de centenas, risco > ganho).
- **Gate:** `cargo test -p forza-db` (incl. `tests/doctor_full.rs`) verde.

## Fase 5 — `gui/lib.rs::run()` (P2, 1–2 dias, risco baixo)

1. **5.a** extrair `handle_response(response, ui)` de `lib.rs:767-1441`
   (~24 braços; `Inventory:768-831` tem 64 linhas). Closure vira 1 linha.
   Idem segundo dispatch `:2566`.
2. **5.b** agrupar 60 `main.on_*` em `wire_inventory/review/bestlaps/detail/settings_debug_logs/run(&main)` —
   padrão já provado por `detail_views.rs`/`ui_state.rs`. Sem tocar em estado
   (sem `UiState` única — `RefCell` por campo é o idiomático Slint).
3. Opcional: aplicação de geometria `:594-696` → `ui_persist::apply_to_window`.
- **Gate:** `cargo check/clippy/test -p forza-gui` verdes + smoke manual.

## Backlog P3/P4 (observar)

- `Page::ops: String → Vec<u8>` (`pdf.rs:516-535,1191-1194`) — só junto de outro toque no PDF.
- Thread-por-job (`worker.rs:1022-1043`), `connection_pool` órfão, pragmas duplicadas
  (`connection.rs`, forçadas por `with_init`), Flate ausente, N+1 review/doctor.
- **Ordem:** 1 → 2 → 3 → 4 → 5. Fases 1–2 um PR cada; Fase 3 em 3 PRs; 4–5 um PR cada.
