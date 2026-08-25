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

- [ ] Fase 2 — Domínio e configuração
- [ ] Fase 3 — SQLite e queries da GUI
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
  retry resolveu nas duas ocorrências.
