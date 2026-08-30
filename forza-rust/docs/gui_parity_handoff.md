# GUI Rust Parity — Plano e Estado (handoff)

**Última atualização:** 2026-08-31
**Objetivo:** GUI Rust funcionalmente igual ou melhor que a Python (`forza/gui/`),
exceto a view Records/Performance (adiada por decisão do usuário — o dashboard
Python será refeito upstream). Deve funcionar de 1080p a 4K (usuário usa QHD).

## Estado por fase

| Fase | Escopo | Status | Commit |
|---|---|---|---|
| A | Modularização (slint: theme/models/components/9 pages; rust: ui_state + detail_views), tema claro legível, layouts adaptativos (min-width 1180, stretch, sem binding loops) | ✅ | `7b043a0` |
| B | Images parity: 7 colunas + sort por header (Rust sobre ROW_CACHE), seleção Ctrl/Shift/Ctrl+A (pointer-event modifiers + FocusScope), Export (rfd picker)/Rescan/Delete c/ confirmação, Scan folder, resumo de seleção, painel lateral c/ hash/semantic/path/duplicate; detail: colunas Run + Model | ✅ | `6d611ab` |
| C | Review parity: ReviewQueueFilter (bucket+reason/outcome/run), 19 campos/caso, reopen_case; worker retorna ReviewOptions dinâmicas; página de 3 painéis (preview/fila/detalhes+ações), ações por motivo (dirty, track combo c/ referência, weather, class, car/driver), atalhos ↑↓/D/C/I/Enter, auto-advance | ✅ | `35e0f99` |
| D | Best Laps: filtros em cascata (track/class/weather/driver/car/source/lap/only-mine), resumo (Tracks/Clean/Dirty/Screenshots/External), merge external_lap_records ativos, grupos Track·Class c/ cor de classe, tintas (mine/external/dirty), sort, Export CSV (forza_output::export_csv), Generate PDF filtrado, Open last PDF, **Import CSV + XLSX (calamine 0.26)** → external_record_imports + external_lap_records com matching de pistas/carros e relatório | ✅ | `d91b051` (D1 `9261fce` · D2 `4a3bade` · D3 `d91b051`) |
| E | Diagnostics: `run_full_doctor` 63 checks c/ severity+count + `DoctorCheckItem{result,count,check,description}` tabela 4 col colorida (`#fde8e7`/`#fdf3d7`/`#e2f5e9`) + badge PASS/WARN/FAIL; Logs c/ busca (filtro lines + `matching line(s)`), Clear tab c/ `rfd::MessageDialog` YesNo truncate, Open log folder via `opener`; Overview tab novo (ping LM Studio `GET /api/v1/models` 1s timeout via `reqwest::blocking`, fast DB `PRAGMA quick_check + foreign_key_check + pending best lap` + `images/available/review_open`); worker `RunFullDoctor`/`RefreshOverview`/`ClearLogs`/`OpenLogFolder`, page `diagnostics` auto-refresh overview; `percent=100 só se !cancelled` + `selected-index=-1` no refresh | ✅ | `pendente` |
| F | Image Debug polish (11 colunas, abas como tabelas), About dialog (versão/build/db/copy diagnostics), status bar (versão · db · schema) | ⬜ | — |

## Arquitetura atual

```
forza-rust/crates/forza-gui/
├── ui/
│   ├── main.slint        # shell: sidebar + composição das páginas (446 linhas)
│   ├── theme.slint       # global Theme (paleta clara, fontes, espaçamentos)
│   ├── models.slint      # structs ImageItem/ReviewItem/BestLapItem/...
│   ├── components/common.slint  # Card, Badge, EmptyState, SortHeaderCell, FilterCombo
│   └── pages/*.slint     # images, process, review, bestlaps, diagnostics,
│                         # image_debug, logs, performance (placeholder), settings, image_detail
└── src/
    ├── lib.rs            # run() + registradores de callback (~890 linhas)
    ├── ui_state.rs       # thread-locals + helpers (set_status, append_run_log, image_items...)
    ├── detail_views.rs   # apply_image_detail/apply_settings/apply_debug_*
    ├── worker.rs         # Request/Response + handle_request + handlers
    └── build.rs          # APP_GIT_HASH/APP_BUILD_TIME (rerun-if-changed em .git)
```

Padrões estabelecidos:
- Propriedades/callbacks ficam na MainWindow; páginas recebem por binding/forwarding.
- `slint::include_modules!()` **uma única vez** (lib.rs); submódulos usam `use crate::{MainWindow, ...}`.
- Tabelas = header clicável (SortHeaderCell top-level) + ListView + TouchArea com
  `pointer-event` (modifiers.ctrl/shift); sort em Rust sobre o cache de linhas.
- Seleção: SELECTED_IMAGE_IDS (ids) + SELECTION_ANCHOR (shift range) + SORT_STATE.
- Worker: Request/Response tipados, uma thread "forza-gui-worker"; runs vivos via
  spawn_extraction próprio thread + RunEvent marshalado.

## Quirks do Slint 1.17.1 descobertos (economize tempo)

1. Componentes **não aninham** dentro de component bodies — top-level only.
2. Propriedade `in property <length> min-width` conflita com o builtin de TouchArea → renomear (`col-min-width`).
3. `selected` do ComboBox entrega o **valor (string)**, não índice.
4. Strings não têm `.split()` nem `.endswith()` — resolver no Rust (campo bool no modelo).
5. Não usar `width: parent.width * X` dentro de HorizontalLayout (binding loop) → `horizontal-stretch`.
6. `Math.mod(a, b)` (não `%`); ternário `cond ? a : b` (não `if/else` em return).
7. `slint::Image`/`SharedString` — setters esperam os tipos do slint (`.into()`).
8. Diálogos nativos: crate **rfd** (já em forza-gui deps).
9. XLSX planejado: crate **calamine** (adicionar em forza-gui ou forza-app).
10. `cargo test` NÃO rebuilda os bins em target/debug; `cargo build` sim. Fechar a GUI
    antes de rebuildar (Access denied no link). `--version`/título mostram o build.

## Workflow do usuário
- Executa SEMPRE via GUI em `target\debug` (feche e reabra após rebuild).
- Rebuild: `cargo build -p forza-cli -p forza-gui` (ou `--release`).
- `forza --version` deve responder `0.1.0+g<hash> built <data>`; run rows gravam a versão.
- CUIDADO: `forza` no PATH é o CLI **Python** pip-instaldo (Scripts\forza.exe) — não confundir.

## Referências Python (para as fases restantes)
- Best Laps: `forza/gui/views/best_laps_view.py` + `controllers/best_laps_controller.py`
  (filtros em cascata: cada combo exclui o próprio constraint; colunas CSV completas em
  best_laps_controller.py:336; PDF gerado das linhas filtradas).
- Import: `forza/gui/controllers/...` + serviço de external records (validação, matching,
  relatório imported/accepted/rejected/unmapped/invalid).
- Doctor view: `forza/gui/views/db_doctor_view.py` (4 colunas, cores).
- Logs: `forza/gui/views/logs_view.py` (busca QTextEdit.find, clear c/ flush de handlers).
- Overview: `forza/gui/views/developer_overview_view.py` (ping LM Studio 1s + fast_db_report).
