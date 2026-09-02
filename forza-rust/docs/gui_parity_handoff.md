# GUI Rust Parity — Plano e Estado (handoff)

**Última atualização:** 2026-09-01
**Objetivo:** GUI Rust funcionalmente igual ou melhor que a Python (`forza/gui/`).
A página Records (placeholder) foi **removida** por decisão do usuário, junto com o
placeholder inacessível de Performance. Deve funcionar de 1080p a 4K (usuário usa QHD).

## Estado por fase

| Fase | Escopo | Status | Commit |
|---|---|---|---|
| A | Modularização (slint: theme/models/components/9 pages; rust: ui_state + detail_views), tema claro legível, layouts adaptativos (min-width 1180, stretch, sem binding loops) | ✅ | `7b043a0` |
| B | Images parity: 7 colunas + sort por header (Rust sobre ROW_CACHE), seleção Ctrl/Shift/Ctrl+A (pointer-event modifiers + FocusScope), Export (rfd picker)/Rescan/Delete c/ confirmação, Scan folder, resumo de seleção, painel lateral c/ hash/semantic/path/duplicate; detail: colunas Run + Model | ✅ | `6d611ab` |
| C | Review parity: ReviewQueueFilter (bucket+reason/outcome/run), 19 campos/caso, reopen_case; worker retorna ReviewOptions dinâmicas; página de 3 painéis (preview/fila/detalhes+ações), ações por motivo (dirty, track combo c/ referência, weather, class, car/driver), atalhos ↑↓/D/C/I/Enter, auto-advance | ✅ | `35e0f99` |
| D | Best Laps: filtros em cascata (track/class/weather/driver/car/source/lap/only-mine), resumo (Tracks/Clean/Dirty/Screenshots/External), merge external_lap_records ativos, grupos Track·Class c/ cor de classe, tintas (mine/external/dirty), sort, Export CSV (forza_output::export_csv), Generate PDF filtrado, Open last PDF, **Import CSV + XLSX (calamine 0.26)** → external_record_imports + external_lap_records com matching de pistas/carros e relatório | ✅ | `d91b051` (D1 `9261fce` · D2 `4a3bade` · D3 `d91b051`) |
| E | Diagnostics: `run_full_doctor` 63 checks c/ severity+count + `DoctorCheckItem{result,count,check,description}` tabela 4 col colorida (`#fde8e7`/`#fdf3d7`/`#e2f5e9`) + badge PASS/WARN/FAIL; Logs c/ busca (filtro lines + `matching line(s)`), Clear tab c/ `rfd::MessageDialog` YesNo truncate, Open log folder via `opener`; Overview tab novo (ping LM Studio `GET /api/v1/models` 1s timeout via `TcpStream`, fast DB `PRAGMA quick_check + foreign_key_check + pending best lap` + `images/available/review_open`); worker `RunFullDoctor`/`RefreshOverview`/`ClearLogs`/`OpenLogFolder` concurrente, page `diagnostics` auto-refresh overview; `percent=100 só se !cancelled` + `selected-index=-1` + robust `database_file` (workspace `data/forza.sqlite3` 693 vs `target/debug` 30) + `count:string` fix | ✅ | `b9a3aef` + `f9eafe5` |
| F | Image Debug polish: 11 colunas (`Image` 280 · `Race Date` 95 · `File` 85 · `Process` 85 · `Best` 100 · `Latest` 100 · `Run` 90 · `Model` 85 · `Attempts` 65 · `Laps` 55 · `Reviews` 60) + filter bar 5 combos + `race-date` no modelo + `artifacts`/`runtime` abas; About dialog (`app-version`/`context-db`/`doctor-summary` + `Copy diagnostics` via `clip`), status bar (`app-version` · `db` · `schema`) em `main.slint:537` | ✅ | `aade3ba` |

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

---

## Rodada de correções (2026-09-01) — truncamentos, DPI, consistência

**F0 — Remoções:** `records.slint` + `performance.slint` apagados (imports, rotas,
`records-*` props/callbacks); `GridText` removido; cópia morta `class_color` (lib.rs)
removida — fonte única `Theme.class-color`; `ui-min-px` default alinhado (12→13).

**F1 — Janela/DPI/persistência (`lib.rs` + `ui_persist.rs`):**
- Save converte px físicos → lógicos via `window.scale_factor()` (bug antigo "scale
  factor 1" que crescia a janela a cada ciclo em displays != 100%).
- `WindowState.maximized` persistido e restaurado (`set_maximized`).
- 1ª abertura (sem `ui_state.json`): tamanho calculado `min(92% work area, 1600) x
  min(88%, 950)` via `GetSystemMetrics(SM_CXFULLSCREEN/CYFULLSCREEN)` (windows-sys,
  feature `Win32_UI_WindowsAndMessaging`); fallback 1400x800.
- Splitters persistem como **rácios** do tamanho lógico da janela
  (`*_ratio`, clamp 0.05..0.95) — layout proporcional entre resoluções; campos
  renomeados, formato antigo ignorado pelo serde.
- Larguras de coluna persistidas de verdade: 9 colunas redimensionáveis expostas no
  `MainWindow` (`images-col-*`, `review-col-*`, `bestlaps-col-*`, `debug-col-image-w`)
  com binding two-way às páginas; keys `images.name`, `review.decision`, etc., clamp
  44..2000. Fallback mal ligado `"images.name"` removido.
- Min window 1240x680.

**F2 — Escala:** tokens geométricos escalados no Theme (`row-h`, `header-h`,
`control-h`, `bar-h`, `badge-h`, `card-pad`, `pad-sm/md`, `splitter-w`,
`statusbar-h`, `log-font`) adotados em headers/splitters/status bar;
`default-font-size: Theme.font-md` na Window (textos sem font-size escalam).

**F3 — Truncamentos (capturas):** banda de grupo Best Laps usa toda a largura
(spacer concorrente removido) + `Theme.text-on-dark`; combo Class min-width 70→100
("TCR" cabe); id do Image Debug com max-width 340 + elide; Laps & Reviews sem o
prefixo repetido da pista; tabela Image Debug rebalanceada (soma fixa 1200→~925,
Rev não corta mais); Attempts: Model 130px/Rejected 100px/Created flexível;
Trigger do Review 160px; label "Status:" no filtro do Review; Rate/ETA mostram "—"
em repouso; filter bar de Images em Flickable horizontal com viewport elástico
(`Math.max(1050px, self.width)`); `log-font` aplicado no Logs (era 10px fixo) com
wrap; EmptyState com `width` nos cards (review/bestlaps/doctor/image_debug/process);
linhas do event log com altura ligada à fonte.

**F4 — Consistência:** `TabBar` compartilhado adotado em Diagnostics, Image Debug e
Image Detail; cores doctor/badge deduplicadas via `Theme.doctor-badge-*` /
`doctor-row-*`; `PageHeader` não adotado foi removido (código morto).

**F5 — Wiring:** `bestlaps-detail-requested` handler completo (abre image-detail via
`BestLapItem.image-file-id`, botão enabled condicional); auto-advance do Review
preserva/avança `REVIEW_INDEX` no reload do filtro corrente (`review-step` morto
removido); `ProcessPage.select-in-images` ligado ao handler raiz; `scan-status`
preenchido no sync do input folder.

**Verificação:** `cargo check -p forza-gui` OK; `cargo test -p forza-gui` 5/5 OK.
Pendente: checklist visual 1080p/QHD/4K@150% e commit.
