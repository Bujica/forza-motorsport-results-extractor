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
- [ ] VS Build Tools with VC workload available to linker (install running)

## Branch strategy

- [x] `dev` branch created from main @ 5e56226 (0.21.0-beta.1 baseline)
- [x] stale worktree/branch `python_to_rust_rewrite` removed
- [ ] `main` stays frozen at the final Python release during migration

## Fase 0 — Baseline e contratos

- [~] selecionar conjunto representativo de screenshots e registrar contagens
      (`fixtures/images/` fica fora do Git; caminhos documentados)
- [~] extrair snapshot normalizado do banco Python para
      `forza-rust/fixtures/python_outputs/` (a DB local já tem os dados; sem
      nova execução LM Studio)
- [ ] salvar CSV/PDF de referência gerados pelo Python 0.21.0-beta.1
- [ ] salvar respostas gravadas do LM Studio (tentativas/artefatos) como
      fixtures de pipeline
- [ ] revisar `docs/contracts/*.md` e catalogar contratos cobertos/não cobertos
- [ ] classificar testes `*_static.py` no mapa de tradução
      (`forza-rust/docs/contracts.md`)
- [ ] auditar índices únicos parciais, triggers, check constraints, defaults e
      ações `ON DELETE` por tabela (`forza-rust/docs/database.md`)
- [ ] identificar campos derivados vs dados de revisão
- [ ] criar `forza-rust/fixtures/README.md` (o que é versionado)
- [ ] registrar tempo atual de abertura da GUI/carregamento da lista
      (medição manual — entrada da Fase 5)

## Fase 1 — Workspace e ferramentas Rust

- [ ] workspace Cargo com os 9 crates compilando vazio
- [ ] `cargo fmt`, `cargo clippy`, `cargo test` verdes
- [ ] política de erros documentada (thiserror por crate, erros de domínio puros)
- [ ] política de logging (tracing + env-filter)
- [ ] convenções de módulos/tamanho registradas
- [ ] CI inicial

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
