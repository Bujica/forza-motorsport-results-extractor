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
      - [ ] pendência Fase 7/8: persistir run_inputs do plano (decisões no
            vocabulário completo incl. unsupported/outside_input), retry-errors
            seleção, integração com LM Studio
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
      - [ ] pendência Fase 8: runtime snapshots/prompt snapshots persistidos,
            unload/load automático quando incompatível, artifacts raw,
            integração run_service completa
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
      - [ ] pendências 8½: persistência de run lifecycle completo
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
      - [ ] pendências F10: Records (adiado por decisão do mantenedor — redesign futuro),
            Performance dashboard, Logs view dedicada
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
  GUI viva 8s; clippy ainda com type-complexity pendente de permitir no
  HashMap de 11 tuplas.
