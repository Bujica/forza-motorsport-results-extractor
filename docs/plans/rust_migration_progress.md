# Rust Migration Progress Checklist

Status: current
Audience: maintainer, developer, LLM
Lifecycle: temporary (deleted when migration completes or is abandoned)
Scope: execution tracking for `2026-08-25_rust_migration_plan.md`
Last verified: 2026-08-25

Companion tracker for the migration plan. Update this file at the end of every
work session: mark completed items, add dated notes for decisions taken outside
the plan text. The plan itself is not edited for progress; only this file is.

Legend: `[ ]` pending, `[~]` in progress, `[x]` done, `[-]` intentionally
skipped (with reason).

## Environment

- [x] rustup stable-x86_64-pc-windows-msvc installed (cargo/rustc 1.98.0)
- [x] VS Build Tools with VC workload available to linker (smoke build OK)
- [x] rustfmt + clippy components installed

## Branch strategy

- [x] `dev` branch created from main @ 5e56226 (0.21.0-beta.1 baseline)
- [x] stale worktree/branch `python_to_rust_rewrite` removed
- [ ] `main` stays frozen at the final Python release during migration

## Fase 0 — Baseline e contratos

- [~] selecionar conjunto representativo de screenshots e registrar contagens
      (`fixtures/images/` fica fora do Git; caminhos documentados) — contagens
      do banco capturadas em counts.json; seleção física de screenshots ainda
      pendente (Fase 6 precisa delas para pipeline)
- [x] extrair snapshot normalizado do banco Python para
      `forza-rust/fixtures/python_outputs/` via
      `tools/export_rust_baseline.py` (schema inventory, counts, referências,
      performance por run; CSV/PDF locais com 1103 linhas / 67 seções;
      50 respostas LM Studio amostradas — 25 aceitas + 25 malformadas)
- [x] salvar CSV/PDF de referência gerados pelo Python 0.21.0-beta.1
      (local-only, fora do Git conforme fixtures/README.md)
- [x] salvar respostas gravadas do LM Studio como fixtures
      (`fixtures/model_responses/`, local-only)
- [~] revisar `docs/contracts/*.md` e catalogar contratos cobertos/não cobertos
      (catálogo criado em `forza-rust/docs/contracts.md`; leitura fina dos
      docs de contrato acontece crate a crate nas fases seguintes)
- [x] classificar testes `*_static.py` no mapa de tradução
      (`forza-rust/docs/contracts.md`)
- [x] auditar índices únicos parciais, triggers, check constraints, defaults e
      ações `ON DELETE` por tabela (`forza-rust/docs/database.md`;
      achado: zero triggers no baseline)
- [x] identificar campos derivados vs dados de revisão
      (`forza-rust/docs/database.md`)
- [x] criar `forza-rust/fixtures/README.md` (o que é versionado)
- [ ] registrar tempo atual de abertura da GUI/carregamento da lista
      (medição manual — entrada da Fase 5; requer medição na máquina do
      mantenedor)

## Fase 1 — Workspace e ferramentas Rust

- [x] workspace Cargo com os 9 crates compilando vazio
      (`forza-rust/`, edition 2024, lints compartilhados, rust-toolchain.toml,
      assets copiados para `forza-rust/assets/`)
- [x] `cargo fmt`, `cargo clippy`, `cargo test` verdes
- [~] política de erros documentada (thiserror entra na Fase 2 junto do
      domínio; lints workspace já proíbem unsafe e warn unwrap/expect)
- [ ] política de logging (tracing + env-filter) — entra com a Fase 2/CLI
- [ ] convenções de módulos/tamanho registradas
- [x] CI inicial (`.github/workflows/rust.yml`: fmt/clippy/test no windows-latest)

## Fases 2–11

- [~] Fase 2 — Domínio e configuração
      - [x] enums persistidos (`enums.rs`, valores explícitos via macro
            `value_enum!`, `as_str`/`from_value`/`FromStr`)
      - [x] lap.rs: parse/format ms, dirty symbols (+FE0F), sanitize driver,
            weather, °F→°C (string+comma), extract_class_letter,
            detect_race_class + TCR_CARS
      - [x] race_class.rs (CLASS_ORDER + CLASS_COLORS), text_utils.rs
      - [x] difflib.rs: porte fiel de SequenceMatcher.ratio +
            get_close_matches (sem autojunk; sem lookbehind — crate regex
            não suporta)
      - [x] normalizer.rs (fix_track_name 6 passos, fix_car_name 3 passos),
            review_rules.rs, car_names.rs (car_match_key/canonicalização),
            ordering.rs (ordered_lap_key), reference_data.rs (assets
            embutidos via include_str!)
      - [x] GOLDEN: `tools/export_domain_golden.py` gera vetores do Python
            real → `fixtures/expected/domain_golden.json`; teste Rust
            `domain_golden.rs` valida equivalência semântica (15 checks).
            Divergências reais pegadas e corrigidas: CLASS_ORDER["Unknown"]=12
      - [x] forza-config: structs completas, defaults Python idênticos,
            strict vs lenient+warnings, validate_config com mensagens iguais,
            prompts registry; 7 testes de contrato INI
- [~] Fase 3 — SQLite e queries da GUI
      - [x] schema Rust completo gerado do inventário do baseline Python:
            `tools/generate_db_schema.py` → `schema_ddl.rs` (17 tabelas + 32
            índices, DDL byte-fiel; STRICT tables respeitadas)
      - [x] versionamento via `PRAGMA user_version` (decisão única registrada;
            Empty/Current/Incompatible; recusa banco de versão estrangeira)
      - [x] contrato de conexão (WAL + busy_timeout 5s + foreign_keys ON)
            com testes próprios, inclusive no pool r2d2
      - [x] repositories mínimos p/ seed e testes (images/runs/laps/reviews)
            com `seed_demo_database`
      - [x] query de inventário da GUI com projeção derivada de
            processing_status fiel a `image_reads.py` (latest result →
            skipped-via-latest-input → unprocessed), filtros por status,
            run_id, best_lap_status, missing-files, ordenação estável
      - [x] doctor básico: integrity_check, foreign_key_check, schema_state
      - [x] CLI: `config-check`, `maintenance db-status/db-doctor/db-upgrade/
            db-reset` funcionando end-to-end (smoke em temp dir)
      - [x] testes: connection contract (3), schema lifecycle (5),
            constraints (8: índices parciais ×2, RESTRICT/CASCADE/SET NULL,
            vocabulários), gui_inventory (5), doctor_basic (3) = 24 testes
      - [ ] pendência Fase 3½/Fase 8: repositories completos (frontier,
            review refresh/corrections, artifacts), checks de contadores de
            run no doctor, validação de paths graváveis no config-check
- [ ] Fase 4 — Vertical slice da GUI
- [ ] Fase 5 — Benchmark da lista de imagens
- [ ] Fase 6 — Imagens e planejamento
- [ ] Fase 7 — Cliente LM Studio e pipeline
- [ ] Fase 8 — Runs, revisão e rebuild
- [ ] Fase 9 — CSV, PDF e telas de resultado
- [ ] Fase 10 — GUI completa
- [ ] Fase 11 — Empacotamento e acabamento

## Session log

### 2026-08-25

- Sessão 1: ambiente preparado (rustup OK, Build Tools em background), branch
  `dev` criada a partir do baseline 0.21.0-beta.1, início da Fase 0.
- Sessão 2: Fase 0 quase completa — ferramenta `tools/export_rust_baseline.py`
  extrai baseline da DB existente sem LM Studio (1103 best-laps → CSV/PDF de
  referência, 50 respostas amostradas); auditoria estrutural do schema em
  `forza-rust/docs/database.md`; catálogo de tradução dos 78 guards estáticos
  em `forza-rust/docs/contracts.md`. Fase 1 completa — workspace com 9 crates,
  fmt/clippy/test verdes, CI inicial. Pendências: screenshots de fixture
  (Fase 6), medição manual de tempo da GUI (Fase 5), políticas de
  erro/logging documentadas junto da Fase 2.
- Nota: erro 10013 intermitente ao baixar componentes de static.rust-lang.org;
  retry resolveu nas duas ocorrências. Mantenedor esclareceu: é o firewall do
  Windows pedindo autorização para novos programas; aguardar alguns segundos
  e tentar de novo.
- Sessão 3: Fase 2 implementada e verde (fmt/clippy -D warnings/test 18/18).
  Lição técnica: crate `regex` do Rust não tem lookbehind — reescrever padrões
  Python com grupos de captura equivalentes; `LazyLock::new` em static exige
  const-context, então helpers de regex viram macro (`lazy_regex!`).
  Pendência da Fase 2 encerrada: nenhuma bloqueante; validação de paths
  graváveis (os.access W_OK) ficou de fora do validate_config Rust por agora
  — decidir abordagem Windows quando a CLI consumir (Fase 2½/Fase 3).
- Sessão 4: Fase 3 implementada. Lições técnicas: (1) o baseline usa STRICT
  tables — `run_inputs.id` é INTEGER enquanto todo o resto é VARCHAR/UUID;
  (2) `created_at` etc. são NOT NULL SEM default no DDL (o Python preenche
  no cliente) — repositórios Rust precisam sempre fornecer timestamps;
  (3) referência mútua attempts↔results exige criação sob foreign_keys=OFF;
  (4) CASE...ELSE sobre coluna NULL engole o COALESCE seguinte — projeção
  precisa de WHEN ... IS NULL THEN NULL. CLI de manutenção operacional.
  Próximo: Fase 4 (vertical slice Slint da GUI).
