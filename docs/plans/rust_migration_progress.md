# Rust Migration Progress Checklist

Status: current
Audience: maintainer, developer, LLM
Lifecycle: temporary (deleted when migration completes or is abandoned)
Scope: execution tracking for `2026-08-25_rust_migration_plan.md`
Last verified: 2026-08-26

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
- [~] Fase 4 — Vertical slice da GUI
      - [x] abertura da janela (Slint, ui/main.slint compilado por
            slint-build em build.rs) — smoke real: processo vivo 6s, sem
            crash, config+sqlite+query no caminho
      - [x] carregamento de configuração (forza-config com validação e
            erros claros se DB não existe)
      - [x] abertura do SQLite via contrato de conexão
      - [x] consulta da lista de imagens pelo ImageInventoryService
            (forza-app), nunca SQL direto na GUI
      - [x] filtro básico por processing status (ComboBox → request tipada)
      - [x] seleção de imagem + painel de detalhes (dados já carregados,
            sem nova query)
      - [x] logs/mensagens de erro: linha de status com loading/contagem/
            error; tracing-subscriber env-filter no binário
      - [x] worker: thread dedicada com runtime Tokio current_thread;
            requests/responses tipados; retorno via invoke_from_event_loop;
            estado de UI (Rc models) em thread_local — nunca compartilhado
            entre threads
      - [x] subcomando `forza gui` no CLI (contrato §4.8 restaurado com
            #[command(name)] após lint de prefixo)
      - [x] testes headless do worker/service (3): handler puro, filtro,
            round trip de thread com canal tipado
      - [ ] pendências para Fase 10: navegação entre seções, ícones/estilo,
            paginação da lista, testes de contrato de callbacks .slint
- [x] Fase 5 — Benchmark da lista de imagens → MOVIDO PARA O FINAL por
      decisão do mantenedor (comparação Python↔Rust quando ambas as linhas
      estiverem completas; medição manual da GUI Python continua pendente)
- [~] Fase 6 — Imagens e planejamento de execução
      - [x] descoberta recursiva com extensões suportadas e ordenação
            name.lower() (`discovery.rs`)
      - [x] hash sha256hex_size com teste de vetor conhecido
      - [x] metadados via crate image (dimensões/format/mime/color_mode/
            bit_depth estimado) — `inspect_metadata`
      - [x] planejamento com precedência Python exata: hash_failed →
            existing(path-hash) → cached(hash) → batch(seen_in_batch só
            registra NOVOS!) → novo único; flag force ignora conhecimento
      - [x] encode_image_payload: RGB, resize LANCZOS3 se width>max,
            desaturação HSL-lightness ((max+min)/2), PNG encoder direto,
            JPEG com quality honrado, webp lossless (divergência documentada:
            crate image não faz webp lossy), byte_count do payload final
      - [x] semantic_filename com sanitização Windows + cap 150
      - [x] `forza run --dry-run [--force] [--limit N]` no CLI operacional —
            smoke real: 4 arquivos sintéticos, batch dup detectado
            (race_1_copy ↔ race_1)
      - [x] erros por arquivo sem abortar o lote (hash_failure isolado testado)
      - [x] 12 testes novos (discovery/hash/planning/encode/naming/metadata)
      - [~] pendência Fase 7/8: persistir run_inputs do plano (decisões no
            vocabulário completo incl. unsupported/outside_input), retry-errors
            seleção, integração com LM Studio; caminho live já grava file_hash,
            file_name, extensão, path normalizado, tamanho e mtime para entradas
            processadas
- [~] Fase 7 — Cliente LM Studio e pipeline
      - [x] `forza-lmstudio`: RuntimeClient (health/list_models/
            runtime_status com warnings fiéis — physical_batch_size
            uncomparável, context_length ">= desejado", vision, reasoning)
      - [x] backend de extração: payload LM Studio native (system_prompt +
            input[image data_url, text]), retry adaptativo transport →
            json_retry → semantic_retry, attempt records completos,
            request_hash canônico, mensagens redacted
      - [x] performance: PerformanceTracker (slow streak por TPS floor +
            elapsed) com flag reload_before_next (persistência Fase 8)
      - [x] response.rs: clean fences, parse estrito, validação t/e/dr/ca/cl/bl
            com lap times, semantic_retry_issues (track_empty/entries_empty/
            all_best_laps_null)
      - [x] json_repair mínimo e HONESTO — descoberta-chave: as 25 fixtures
            "malformed" reais fazem strict-parse OK hoje; falhavam em
            validação sob regras antigas. Repair cobre só sintaxe observável
            (prose wrap, trailing commas, aspas simples/curvas)
      - [x] GOLDEN 50/50: todas as respostas reais parseiam+validam; accepted
            batem parsed_json armazenado exatamente
      - [x] persistência: insert_attempt_full (evidência completa),
            finalize_result_ok, replay_recorded_response em forza-app derivando
            laps normalizados (track/car/class/weather/temp/dirty) das entries
      - [x] critério atendido: fixture gravada percorre parse → validate →
            attempts → result → laps sem LM Studio (2 testes e2e verdes)
      - [x] live smoke contra LM Studio real (`examples/lm_health.rs`):
            17 modelos, modelo configurado carregado; detectou mismatch REAL
            de eval_batch_size carregado ≠ 1024 desejado (registrar para
            investigar no app Python também!)
      - [~] pendência Fase 8: prompt snapshot já é persistido de forma imutável
            no caminho live, com hash/ID byte-compatíveis ao Python; runtime
            snapshots, unload/load automático quando incompatível, artifacts
            raw e integração run_service completa ainda pendentes
- [~] Fase 8 — Runs, revisão e rebuild
      - [x] CRITÉRIO CENTRAL ATENDIDO (e2e em banco de teste):
            `processar → revisar → corrigir → rebuild` sem nova chamada ao
            modelo (`forza-app/tests/run_flow.rs`) — replay 3 imagens,
            fronteira vencida por volta suja do player (semântica Python),
            review dirty_lap gerado, correção manual aplica+resolve,
            rebuild recomputa tudo e doctor fica saudável
      - [x] FrontierCalculator portado para forza-domain/frontier.rs (puro)
            — incluindo a sutileza de que clean_frontier_rows NÃO filtra
            dirty no lado do player
      - [x] mark_best_laps (latest-run-per-image + winners + status das
            images); simple path sem gamertag
      - [x] review candidates com regras fiéis (dirty&best, weather unknown,
            track unknown/unresolved/not-in-reference, class invalid,
            driver triggers, car empty/not-in-reference) + business_key
            canônica (lap-scoped vs image-scoped vs fallback)
      - [x] upsert preservando decisões do operador; condições sumidas →
            auto_resolved
      - [x] correções manuais: apply_manual_correction aplica na lap
            (normalizando track/car), grava evidence em review_corrections
            (stable_key), resolve case como confirmed
      - [x] RebuildService em forza-app (best laps + reviews + contadores);
            comando CLI `forza rebuild` operacional
      - [~] pendências 8½: persistência de run lifecycle completo
            (pending→running→completed com counters reais), reconciliation
            de runs abandonados, runtime/prompt snapshots no backend live,
            artifacts raw, rain_time_suspicious, mark_best_laps_for_groups
            (scoped), integração run_service completa com backend live
      - [ ] PerformanceService/dashboard/gaps + telas GUI correspondentes →
            planejado junto da Fase 10 (superposição reconhecida no plano)
- [~] Fase 9 — CSV, PDF e telas de resultado
      - [x] CSV byte-fiel ao writer Python: BOM utf-8-sig, CRLF, QUOTE_MINIMAL,
            headers/ordem idênticos, None→vazio, bool capitalizado (True/
            False), floats str()-compatíveis — GOLDEN: bytes idênticos
            contra `export_csv` real do Python
            (`fixtures/expected/output_golden.json`)
      - [x] PDF content plan determinístico (`pdf.rs::build_pdf_plan`):
            data_map track→class→rows com sort (time asc, player antes em
            tie), ordem canônica de tracks via assets, class_order + cores,
            GOLDEN estrutural contra _build_data_map real do Python
      - [x] read model list_clean_flat (best-only join image metadata)
      - [x] comando CLI `forza export [--out FILE]` operacional (CSV;
            smoke em banco vazio → mensagem clara)
      - [x] 2 testes golden novos
      - [ ] pendências Fase 10/11: RENDERER visual do PDF (genpdf/printpdf —
            spike pendente; conteúdo já garantido pelo plan testado),
            records/community merge no plan, artifacts de export,
            abertura do arquivo pela GUI
- [~] Fase 10 — GUI completa
      - [x] navegação sidebar entre seções (Images/Review/Best Laps/
            Diagnostics) com página condicional no Slint
      - [x] Review Queue operacional: buckets open/resolved/all, decisões
            Not-dirty/Dirty aplicam correção + rebuild derivado; Ignore
            resolve como ignorado — tudo via worker tipado
      - [x] Best Laps: tabela clean-flat com highlight mine/dirty + botão
            Rebuild derived state
      - [x] Diagnostics: DB Doctor on-demand com relatório textual
      - [x] worker protocol estendido (ListReviews/DecideCase/IgnoreCase/
            ListBestLaps/RunDoctor/RunRebuild) — handlers puros testáveis
            headless (2 testes de round trip verdes)
      - [x] SMOKE REAL end-to-end: banco criado via CLI, 15 laps seedadas
            das 3 fixtures aceitas reais, `forza rebuild` → 5 winners,
            `forza export` → CSV com dados reais, GUI viva 10s navegável
      - [~] Process view com backend live (10b):
            - [x] `extraction_runner.rs`: thread dedicada + cancel
                  cooperativo entre imagens (Arc<AtomicBool>); eventos
                  tipados Started/Plan/ImageStarted/ImageDone/Progress/Log/
                  Finished/Failed; discovery→plan→run row→inventory
                  decisions (skip/duplicate/hash_failed)→encode→ensure_
                  loaded→extract com attempts persistidos→laps derivados
                  (função compartilhada `derive_and_insert_laps` com o
                  replay)→finalize→counters→mark_best_laps ao final
            - [x] Slint: página Process fiel ao screenshot Python (Run
                  Config com Dry-run/Force checkboxes, Run All/Cancel,
                  info line; Progress com barra custom %/done/total/rate/
                  ETA; Event Log ListView) — ProgressBar não existe no
                  std-widgets atual (barra custom)
            - [x] Dry-run via worker (RunDryRun com input_dir) logando o
                  plano no Event Log; Run All dispara runner real contra
                  o LM Studio configurado
            - [x] 2 testes headless: input vazio termina Finished sem
                  contato com modelo; cancel-before-start → Finished
                  cancelled
      - [~] 10c — Image Detail + Settings editável:
            - [x] forza-db `image_detail.rs`: meta com processing_status
                  derivado (mesma projeção do inventário), laps por
                  image, results (join runs p/ backend/prompt), attempts
                  (ordem created_at DESC, attempt_number ASC) — payloads
                  brutos ficam fora (Image Debug os possui, contrato GUI)
            - [x] review queue ganhou filtro image_file_id (tab Review
                  cases do detail); read facade `load_image_detail` em
                  forza-app monta o bundle completo
            - [x] forza-config `save.rs` + `ini.rs`: porte fiel do
                  ConfigFileService (candidate strict → validate → backup
                  timestamped .bak com sufixo contador → write atômico
                  tmp+replace; INI ordenado próprio preserva ordem/keys
                  desconhecidas, dropa comentários como configparser;
                  prune das legacy keys idêntico; floats repr Python
                  `{:?}` → "45.0"; bools True/False)
            - [x] Settings snapshot (forza-app `services/settings.rs`):
                  30 linhas nos 3 grupos Python com editor/status/options
                  (ranges idênticos), status de paths ok/invalid/missing,
                  pending overrides, mensagem de validação
                  "Configuration errors:\n  • ..." idêntica
            - [x] worker: WorkerContext (Mutex<AppConfig> + config_path) —
                  gamertag sempre lido do cfg vivo (equivalente Rust do
                  live provider callable do contrato configuration.md);
                  LoadImageDetail/LoadSettings/PreviewSettings/SaveSettings
                  com handlers puros testáveis
            - [x] gamertag change → rebuild derivado no próprio save +
                  refresh de Best Laps/Reviews/Inventory e run-info
            - [x] Slint: página Image Detail (preview com Image::
                  load_from_path, badges file/best/processing, 5 tabs
                  Metadata/Laps/Review cases/Extractions/Attempts,
                  Previous/Next/Close navegando ROW_CACHE; botão Details…
                  na página Images); página Settings (tabela Field/Value/
                  Status com headers de grupo, LineEdit p/ text/int/float,
                  ComboBox True/False p/ bool, barra de validação com
                  badge valid/changed/invalid, Discard/Save; load lazy na
                  primeira entrada via page-changed)
            - [x] testes: image detail round trip (2), settings
                  load/preview/save com backup+recompute+invalid (1),
                  snapshot rows/pending/override/path-status (4), ini
                  parse/render (4), save INI (5)
      - [~] 10d — retry-errors + Pause:
            - [x] RunControl cooperativo (`forza-app/src/services/run_control.rs:1`)
                  com checkpoint (pause bloqueia entre fases/imagens, cancel vence);
                  `retry_errors` mutuamente exclusivo com `force` (mensagem Python);
                  `list_failed_images_for_retry` (`forza-db`) + `insert_processed_input`
                  com `process_reason` em `run_inputs`
            - [x] GUI Process: checkbox Retry habilitada com exclusão mútua contra Force,
                  botão Pause/Resume com estado `run-paused` e `toggle-pause`
            - [x] CLI `forza run --retry-errors` no dry-run com seleção real
            - [x] testes retry (3) + runner pause/force×retry (3)
      - [~] 10e — Image Debug com deeplink:
            - [x] `forza-db/src/image_debug.rs:1` list + detail (counts, ROW_NUMBER latest),
                  `forza-app/src/services/image_debug.rs:1` filtragem post-fetch
            - [x] worker `ListImageDebugCases`/`LoadImageDebugDetail`/`LoadImageDebugByResult`
            - [x] Slint página Image Debug (lista + 8 tabs + result ComboBox + deeplink
                  "Open image debug" no Image Detail); navegação lazy via page-changed
            - [ ] testes headless de round trip do Image Debug (pendente)
      - [~] 10f — Logs view dedicada:
            - [x] worker `LoadLogs` lê `log_file` + irmão `_errors` com truncagem 200KB
            - [x] Slint página Logs (Application Log / Errors, Reload, lazy via page-changed)
      - [~] 10g — Performance placeholder:
            - [x] sidebar "Performance" + página com policy atual e nota de métricas live
      - [ ] pendências F10: Records (adiado por decisão do mantenedor — redesign futuro)
- [~] Fase 11 — Empacotamento e acabamento
      - [x] build dev ok (6.3s), assets embutidos via include_str!, slint-build, config inicial via db-upgrade
      - [x] máquina limpa smoke (temp dir, db-upgrade → dry-run → GUI viva 8s)
      - [ ] build release completo (pesado, adiado)
      - [ ] renderer visual PDF (genpdf), benchmark final (Fase 5)
      - [ ] bump versão 0.1.0 → 0.21.0-beta.x, THIRD_PARTY licenças, docs uso

## Auditoria de equivalência funcional — 2026-08-26

- [x] comparação controlada Python/Rust das mesmas cinco imagens por hash,
      usando `qwen3.6-35b-a3b`; respostas `raw_response` idênticas byte a byte
      e JSONs semanticamente iguais
- [x] integridade da DB Rust verificada: `integrity_check = ok`, sem órfãos
      de foreign key, resultados/tentativas aceitos nas cinco imagens
- [x] corrigir projeção para `lap_records`: entradas sem `best_lap` são
      descartadas; piloto é sanitizado; classe da sessão é calculada sobre as
      entradas válidas; `lap_index` segue a convenção Python
- [x] alinhar a projeção persistida com Python em DBs de teste equivalentes:
      nova execução Rust produziu 47/47 laps idênticos à execução Python,
      incluindo `is_best_lap`/dirty após normalização dos campos comparados
- [x] corrigir metadados live: cabeçalho de run sem `seed-*`; `run_inputs`
      processados gravam metadados do arquivo; tentativas/resultados gravam
      formato, MIME, dimensões e bytes do payload enviado
- [~] persistir prompt/runtime snapshots, artifacts e ciclo de vida completo
      no caminho live: prompt snapshot concluído e validado contra o hash Python;
      snapshot preflight do runtime implementado antes de `ensure_loaded`,
      pendem smoke real contra LM Studio, artifacts e lifecycle
- [ ] implementar Performance real; a tela atual é somente placeholder
- [ ] completar renderer visual PDF, artifacts de export e testes headless de
      Image Debug
- [ ] executar matriz final de equivalência e benchmark da GUI
- [x] decisão: DBs atuais são somente ambientes de teste; não reparar nem
      migrar retroativamente. A validação final usará DBs novas e descartáveis,
      recriadas do zero em Python e Rust.

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
- Sessão 5: Fase 4 implementada e smokeada (janela real abre e consulta o
  banco). Lições técnicas: (1) Slint não aceita modificadores `public` em
  callbacks/properties — já são expostos por padrão; ListView vem de
  std-widgets; (2) `invoke_from_event_loop` exige Send: estado de UI em Rc
  mora em thread_local! da UI thread, nunca capturado pelo worker;
  (3) Weak<MainWindow> é Send e é a ponte correta worker→UI; (4) lints do
  workspace (forbid unsafe_code, unwrap warn) precisam ser sobrescritos no
  crate GUI porque o código gerado pelo slint-build viola ambos; (5) clippy
  pede renomear variantes com prefixo comum (`Db*`) — preservar contratos
  CLI kebab-case com #[command(name)] em vez de renomear. Próximo:
  Fase 5 benchmark da lista + depois pipeline.
- Sessão 6: Fase 5 MOVIDA para o final (decisão do mantenedor: app
  funcional primeiro, comparações depois). Fase 6 implementada. Lições:
  (1) ordenação Python name.lower() coloca "a.jpg" antes de "a.png" — o
  golden mindset evitou "corrigir" o Rust para a ordem errada do teste;
  (2) seen_in_batch só registra NOVOS: existing nunca vira canônico de
  batch-duplicate (semântica sutil do plan_images confirmada no fonte);
  (3) image 0.25: PngEncoder::write_image usa ExtendedColorType (.into()) e
  ordem (buf,w,h,color); JpegEncoder honra quality; webp é lossless-only;
  (4) thiserror rejeita campo String chamado source.
- Sessão 7: Fase 7 implementada. ACHADO IMPORTANTE: as 25 respostas
  "malformed" do baseline passam na validação ATUAL do Python — eram
  rejeições de regras antigas; json_repair real nunca precisou consertar
  sintaxe nelas. Porte do repair ficou mínimo e cobre só o observado.
  Live smoke contra LM Studio local detectou eval_batch_size carregado
  diferente do desejado (1024) — vale verificar no Python se esse warning
  também aparece lá (deve, mesmo código de comparação). Lições técnicas:
  (1) tokio::main exige feature rt-multi-thread quando flavor default;
  (2) invoke_from_event_loop já validado na Fase 4 reaplicado no worker do
  backend assíncrono; (3) clippy let-chains: edition 2024 suporta if let &&
  condição — usar em vez de ifs aninhados.
- Sessão 6b: orza run --dry-run smokeado com imagens sintéticas reais —
  batch duplicate detectado corretamente entre arquivos idênticos.

- Sessão 8: Fase 8 núcleo concluída — critério e2e verde. ACHADO DE
  SEMÂNTICA: clean_frontier_rows NÃO filtra dirty no lado do player; volta
  suja define o limite, vence a fronteira e é exatamente por isso que o
  review dirty_lap existe (impacto em output). Corrigir dirty não altera o
  tempo — a lap corrigida segue dominando legitimamente. CLI ganhou
  orza rebuild. Pendências movidas para 8½/Fase 10 conforme checklist.

- Sessão 9: Fase 9 implementada com estratégia plan-vs-render: o CONTEÚDO
  do PDF (a lista) é uma estrutura tipada determinística testada contra
  golden das funções Python REAIS (_build_data_map + ordering + cores); o
  RENDERER visual fica para F10/11 (spike genpdf/printpdf pendente). CSV
  byte-idêntico confirmado. Lições: (1) Python csv usa utf-8-sig (BOM) e
  CRLF; bool vira True/False capitalizado via str(); floats str() mantêm
  .0; (2) source_file vive em lap_records, race_date em image_files —
  conferir PRAGMA antes de escrever JOINs; (3) sort do bucket é por
  time_sec numérico, nunca pela string.

- Sessão 10: Fase 10 parcial — shell multi-página operacional consumindo
  services reais (review decisions disparam rebuild derivado). Smoke e2e:
  15 laps das fixtures reais → rebuild → export CSV → GUI navegando.
  Lições Slint: (1) ListView precisa dimensões x/y/w/h via parent explícito
  (binding loop senão); (2) sem public em callbacks; (3) font-family
  monospace não existe; (4) LocalKey<OnceCell> exige .with() para get/set.

- Sessão 11: 10b Process view live implementado. Runner em thread própria
  (isola o worker de requests), cancel cooperativo entre imagens, eventos
  tipados marshaled via invoke_from_event_loop, laps derivados por função
  compartilhada com o replay. Slint: ProgressBar inexistente no std-widgets
  → barra custom; CheckBox ok. 2 testes headless do runner.

- Sessão 12 (2026-08-26): 10c Image Detail + Settings editável completos.
  Screenshots da GUI Python (7-Image Details/6-Settings) usados como
  referência visual. Lições técnicas: (1) ListView como filho direto de
  VerticalLayout não aceita x/y (o layout define) — envolver em Rectangle
  absoluto com dimensões parent-based; (2) crate configparser perde ordem
  e keys desconhecidas → INI ordered reader/writer próprio reproduzindo o
  comportamento observável do configparser Python (ordem preservada,
  comentários descartados, `key = value`, linha em branco por seção);
  (3) f64 com `{:?}` reproduz str(float) do Python ("45.0") — helper
  py_float; (4) os keys editáveis usam prefixo LÓGICO llm.* mesmo para a
  seção [lmstudio] (o _apply_llm do Python trata workers + todos os
  campos do backend num só dispatcher); (5) propagação de gamertag via
  WorkerContext com Mutex<AppConfig> — handlers sempre leem o cfg vivo,
  equivalente Rust do live provider callable; save com mudança de
  gamertag dispara rebuild no worker e a resposta atualiza header/
  run-info/RUN_CONFIG na UI; (6) desvio consciente documentado: o Image
  Detail carrega os summaries das 5 tabs num único round trip (leitura
  limitada e pequena, ≤13 laps típicos) — payloads pesados (raw response,
  parsed JSON) continuam fora e serão da página Image Debug; (7) Slint
  sem split de string → options de choice ficariam impossíveis como
  modelo dinâmico de ComboBox; text/int/float usam LineEdit (input-type
  number/decimal) e bool usa ComboBox True/False fixo. Smoke real: GUI
  viva 8s com banco novo via db-upgrade; fmt/clippy -D warnings/test
  workspace 100% verdes. Próximo: retry-errors + Pause no Process,
  depois Image Debug com deeplink.

- Sessão 13 (2026-08-26): 10d retry-errors + Pause no Process completos.
  RunControl (`forza-app/src/services/run_control.rs:1`) com checkpoint
  cooperativo (pause bloqueia entre fases/imagens, cancel vence pause —
  semântica Python `RunControl`). Runner ganhou `retry_errors: bool` +
  validação `force×retry` mutuamente exclusivos, seleção real via
  `list_failed_images_for_retry` (`forza-db/src/repositories/images.rs:36`)
  (latest result `error` + `file_status='available'`, ROW_NUMBER tiebreak
  `created_at DESC, id DESC`), `process_reason` gravado em `run_inputs`
  via `insert_processed_input` (`forza-db/src/repositories/runs.rs:40`) e
  checkpoint antes do loop. GUI Process: checkbox Retry habilitada com
  exclusão mútua contra Force, botão Pause/Resume com `run-paused` e
  `toggle-pause`, RunControl em `thread_local!` (`forza-gui/src/lib.rs:506`);
  Slint `forza-gui/ui/main.slint:215` com `run-paused` e estado "Paused".
  CLI `forza run --retry-errors` lista seleção real no dry-run e recusa
  `force×retry` (mesma mensagem Python). Testes: 3 casos retry (only-latest-
  error, older-ok vs newer-error) + 3 runner (empty, cancel, force×retry,
  retry vazio, pause bloqueia e cancel libera). Smoke GUI viva 8s.

- Sessão 14 (2026-08-26): 10e Image Debug com deeplink iniciado. Leitura
  completa do `forza/gui/views/image_debug_view.py:1` e
  `controllers/image_debug_controller.py:1` + reads Python
  `application/gui_read/image_debug_reads.py:1`: contrato lista sem auto-
  load do primeiro detalhe, seleção carrega só tab visível, deeplink
  preserva subtab. Rust: `forza-db/src/image_debug.rs:1`
  (list_image_debug_cases + get_image_debug_detail +
  get_image_debug_detail_by_result, counts por imagem, ROW_NUMBER latest),
  `forza-app/src/services/image_debug.rs:1` (filtragem post-fetch
  `matches` idêntica ao Python), worker `ListImageDebugCases`/
  `LoadImageDebugDetail`/`LoadImageDebugByResult` (`forza-gui/src/worker.rs:80`),
  Slint página Image Debug com lista + header + result ComboBox +
  8 tabs (Overview/Metadata/Results/Attempts/Response/Parsed/Laps&Reviews/
  Timeline) e deeplink "Open image debug" no Image Detail. Compila e smoke
  GUI viva 8s; clippy type-complexity permitido no HashMap de 11 tuplas.

- Sessão 15 (2026-08-26): 10f Logs view dedicada.
  Worker `LoadLogs` (`forza-gui/src/worker.rs:330`) lê `log_file` +
  `*_errors.log` (irmão com `_errors` no stem, Python
  `logs_view.py:212`), truncagem 200KB, erro amigável se ausente.
  Slint página Logs (`forza-gui/ui/main.slint:640`) com header Reload,
  tabs Application Log / Errors (in-out `logs-tab`), texto word-wrap;
  lazy load via `page-changed` ("logs"). Smoke com `app.log`/`app_errors.log`
  sintéticos.

- Sessão 16 (2026-08-26): 10g Performance placeholder.
  Sidebar ganhou "Performance" (`forza-gui/ui/main.slint:217`), página com
  policy atual (performance_tps_floor / reload_elapsed / reload_streak)
  e nota "live metrics aparecerão após runs — history em Image Debug →
  Attempts". Sem worker adicional (histórico já em attempts). Compila,
  fmt/clippy/test verdes, GUI viva 8s.

- Sessão 17 (2026-08-26): Fase 11 parcial — Empacotamento verificado.
  `cargo build` dev ok (6.3s), `cargo check` release ok, assets em
  `forza-rust/assets/` (cars/tracks/prompt) embutidos via `include_str!`,
  `forza-gui/build.rs:5` slint-build, Slint royalty-free (MIT, já em
  Cargo.lock), `forza_config.ini` criado via `db-upgrade` em máquina
  limpa (temp dir). Versão workspace `0.1.0` (Python 0.21.0-beta.1, bump
  pendente para release). CLI `forza --help` lista todos subcomandos
  (gui/run/rebuild/export/maintenance). Smoke máquina limpa:
  `forza maintenance db-upgrade` → `forza run --dry-run` → GUI viva 8s.

- Sessão 18 (2026-08-26): auditoria controlada da DB Rust contra uma execução
  Python `--force` com o mesmo modelo e prompt. As cinco respostas brutas foram
  idênticas byte a byte e os JSONs semanticamente iguais. A projeção Rust ainda
  diverge: mantém seis entradas sem `best_lap`, usa convenções diferentes em
  `race_class`/`is_best_lap`/`lap_index` e não preenche metadados live completos
  (`run_inputs`, payload, snapshots e cabeçalho sem seed). O plano ganhou a
  seção 10 com backlog P0/P1/P2 para equivalência funcional, GUI Performance,
  PDF, validação e benchmark.
  Pendente: `cargo build --release` completo (pesado, adiado), `genpdf`
  renderer visual do PDF, benchmark final (Fase 5).

- Sessão 19 (2026-08-26): Fase A iniciada no caminho compartilhado por live e
  replay (`extraction_replay.rs`). A projeção agora descarta `bl` inválido,
  sanitiza pilotos, calcula `race_class` via `detect_race_class` sobre entradas
  válidas, trata track vazio/ambíguo e usa `lap_index` zero-based. Teste de
  contrato adicionado para filtragem/classe/índice. Gates: workspace `cargo test`
  e `cargo clippy --workspace --all-targets -- -D warnings` verdes. A regra
  global de `is_best_lap` fica para comparação em DBs novas equivalentes.

- Sessão 20 (2026-08-26): persistência live de metadados do run concluída.
  O cabeçalho deixa de depender dos valores `seed-*`; `run_inputs` processados
  agora registram hash, nome, extensão, path normalizado, tamanho e mtime; e
  tentativas/resultados registram formato, MIME, dimensões e bytes da imagem
  enviada. Teste de contrato cobre a substituição dos defaults. Commit
  `936fd66`.

- Sessão 21 (2026-08-26): snapshot imutável do prompt concluído. O caminho
  live grava `prompt_snapshots`, liga `extraction_runs.prompt_snapshot_id` e
  usa hash canônico byte-compatível com Python (`0a9cd9...c945977`). Teste
  explícito valida a identidade Python/Rust; fmt, testes direcionados e
  clippy workspace passaram. Commit `38bc050`. Próximo: snapshot de runtime
  LM Studio, artifacts e lifecycle completo.

- Sessão 22 (2026-08-26): snapshot preflight do runtime implementado. O
  backend reutiliza `RuntimeClient::list_models`, identifica o modelo
  configurado e a primeira instância carregada, e persiste capacidades,
  metadados e configurações desejada/efetiva em `model_runtime_snapshots`
  antes do primeiro `ensure_loaded`; runs sem imagens não fazem contato com
  LM Studio. Gates direcionados e clippy workspace verdes. Próximo: executar
  smoke com LM Studio real e persistir artifacts/lifecycle.

- Sessão 23 (2026-08-26): smoke real completo executado com o binário Rust
  recompilado. Run `20260826_190320_rust`: 5/5 resultados OK, 47 laps, todos
  os `run_inputs`, payloads, prompt/runtime snapshots e lifecycle gravados.
  Comparação estruturada contra Python `20260826_175250_9beb10b2`: 47/47
  registros coincidentes, 0 somente-Python e 0 somente-Rust. O preflight
  encontrou o modelo configurado carregado e saudável. Permanecem pendentes
  artifacts raw, persistência de Performance e validação visual do PDF.

- Sessão 24 (2026-08-26): Images/Best Laps GUI corrigidos. Images agora
  carrega opções dinâmicas de pista/run, aplica filtros equivalentes aos
  vocabulários Python (arquivo, melhor volta, duplicata e processamento) e
  mantém a seleção dinâmica durante refresh; o painel ganhou stretch vertical
  para o `ListView` ocupar a área disponível. Best Laps passou a ser solicitado
  no carregamento inicial e ao entrar na página. Testes headless cobrem opções,
  filtros, round-trip do worker e projeção de melhores voltas. Gates: fmt,
  `cargo test -p forza-db --test gui_inventory`, `cargo test -p forza-app`,
  `cargo test -p forza-gui --test worker_round_trip`, clippy workspace e
  `cargo build -p forza-gui` verdes.

- Sessão 25 (2026-08-26): corrigido o fluxo de inventário para arquivos
  adicionados após o último run. O refresh da GUI agora sincroniza a pasta
  `paths.input_dir` com `image_files` (hash, metadados, status disponível e
  vínculo de duplicata), sem contato com o LM Studio; antes ele apenas relia
  a DB. A seleção em Images agora carrega o mesmo preview usado em Image
  Detail. Os dois previews usam `image-fit: contain` com dimensões limitadas
  ao card, evitando renderização no tamanho intrínseco original. Build e
  testes direcionados passaram; confirmar visualmente executando o novo
  `forza-gui.exe` a partir de `forza-rust/target/debug`.

- Sessão 26 (2026-08-26): fechada a lacuna funcional de seleção e organização
  em Images. A lista agora mantém seleção múltipla por `image_file_id`, exibe
  a contagem, permite limpar a seleção e oferece `Process selected`, que limita
  a descoberta da run aos arquivos selecionados (respeitando Force/Retry).
  `Rename` foi conectado ao worker: usa `semantic_name`/nome atual, saneia
  nomes Windows, evita sobrescrever destinos e atualiza o caminho na DB.
  Best Laps ganhou estado vazio explícito; a DB de teste atual contém 15
  registros `is_best_lap=1`, portanto o carregamento deve exibir linhas após o
  binário ser recompilado. `cargo check`, Clippy, testes direcionados e
  `cargo build -p forza-gui` passaram.

- Sessão 27 (2026-08-26): corrigida a classificação de imagens recém-
  inventariadas. `known_hashes`/`known_path_hashes` agora consultam apenas
  imagens com resultado final (`ok`/`error`), alinhando o planner ao Python;
  uma imagem nova selecionada em Images não vira mais `skipped` apenas por
  ter sido registrada no refresh. O cartão Best Laps recebeu altura explícita
  para impedir o colapso visual do `ListView`; a consulta já retornava as 15
  linhas. Build GUI passou após o ajuste.
