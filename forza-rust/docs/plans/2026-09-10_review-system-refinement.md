# Proposta: sistema de review refinado (pós-migração)

**Data:** 2026-09-10
**Premissa (revista):** fase de desenvolvimento, **sem compatibilidade com DBs
antigos e sem preservação do DB atual** — DBs regeneram das imagens. Plano
reescrito como se fosse do zero: sem tolerância a legado, sem migração de
dados, DDL editado in place (sem bump de versão; DBs velhos acusam
`schema_drift` e são regenerados — comportamento desejado).

---

## 1. Diagnóstico do estado atual

Estados: `open → resolved | ignored | auto_resolved`. Outcomes:
`pending → confirmed | model_error | ignored`.

Divergências reais encontradas (além da paridade, agora tratadas como bugs):

| # | Achado | Gravidade |
|---|---|---|
| D1 | `decide` sempre grava `outcome='confirmed'`; Python computa `confirmed` sse valor == modelo, senão `model_error`, e classifica `error_type` (`{field}_wrong`, `dirty_lap_false_positive/negative`) + `resolution_note=decision:{field}={value}`. Rust não grava `error_type`/`note` nunca. Checks `model_error_*` do doctor são **código morto** em DBs escritos pelo Rust | média — corrompe a taxonomia de erros |
| D2 | Rust nunca **reabre** `auto_resolved` quando a chave retorna; Python reabre (resetando outcome). Caso auto-resolvido jamais ressurge no Rust | média — mascara regressões reais |
| D3 (fixo em `a72aba3`) | auto-resolve não carimbava `resolved_at`/note; display mostrava `pending` | baixa — corrigido |

## 2. Análise do `ignore case` (pedido explícito)

Função única real: **dismiss sem efeitos colaterais** — sem `review_corrections`,
sem seed de catálogo, sem mutação de laps, sem rebuild (só flag sync).
Tudo o mais (`reopen`, filtro, contagem) o trata como terminal genérico.

Contra manter:
- 4º status + outcome dedicado + bucket de filtro + branch de reopen + 2
  entradas de vocabulário em CHECKs — custo conceitual permanente.
- Substitutos cobrem os casos: valor correto → `decide` (confirmed/model_error);
  condição sumiu → `auto_resolved`; imagem ilegível → caso fica `open`
  (honesto: ainda pendente) ou deleta-se a imagem.
- `review_case_count`, flags sync e doctor não dependem de `ignored`
  (só o citam em listas `IN`).

Risco de remover: operador perde "esconder sem decidir". Julgamento: esconder
trabalho não é estado — `open` é a representação honesta. **Recomendo remover.**

## 3. Modelo proposto

```
status:  open ──decide──▶ resolved        outcome: pending ──▶ confirmed | model_error
              ╰─reopen───╲                  (comparação normalizada modelo × corrigido,
               ╭─reopen───╱                   + error_type classificado + note)
               │                          open ──▶ nunca tem outcome ≠ pending
auto_resolved ◀──condição sumiu──┘         auto_resolved ──▶ display mostra status
     │  (resolved_at + note=no_longer_detected)
     └──condição voltou──▶ open (reopen paridade D2)
```

Regras:
1. **`decide` classifica outcome** (`_decision_outcome` portado como regra nossa,
   não paridade): igual-normalizado → `confirmed`, diferente → `model_error`;
   `error_type` (`{field}_wrong`, `dirty_lap_false_positive/negative`);
   `resolution_note = decision:{field}={value}`. Ativa os checks `model_error_*`.
2. **Auto-resolve** como hoje + `resolved_at`/note (feito) + display mapping (feito).
3. **Reopen paridade D2**: chave retornada reabre `auto_resolved → open`,
   `outcome → pending`, atualiza links/trigger/model_value. Teste dedicado.
4. **Remover ignore por completo (clean-slate)**:
   `ignore_case()`, `Request::IgnoreCase` + handler, botão, bucket `"ignored"`
   do filtro (`review.slint` vira `open|resolved|all`), `"ignored"` do outcome
   hardcoded (`worker.rs`), `IN ('open','resolved','ignored','auto_resolved')`
   → `IN ('open','resolved','auto_resolved')` no exists-check.
5. **Shrink de DDL (sem migração)**: `ck_review_cases_status_vocab` →
   `('open','resolved','auto_resolved')`; `ck_review_cases_outcome_vocab` →
   `('pending','confirmed','model_error')`. `ImageFlagStatus` e
   `ck_image_flags_status_vocab` **intocados** (flags são outra entidade;
   flags de operador continuam podendo ser `ignored`).
   `enums.rs`: remover `ReviewCaseStatus::Ignored` e `ReviewOutcome::Ignored`
   (+ testes `VALUES`); nada no código usa as variantes (só literais).
   Doctor (`status.rs`, `schema.rs`) acompanha automaticamente via DDL/vocab.
6. **Buckets**: `open` / `resolved` (= resolved+auto_resolved) / `all`.
   Filtro outcome: `pending|confirmed|model_error`.
7. **Inalterado**: corrections + seed de catálogo, flags sync (só open),
   `review_case_count` (só open), rebuild em transação, `display_outcome`.
   `reopen_case` mantém predicado `status <> 'open'` (genérico, sem branch).

## 4. Arquivos a tocar

- `forza-db/.../reviews.rs`: reopen-on-return em `upsert_review_cases`;
  exists-check sem `'ignored'`.
- `forza-db/.../corrections.rs`: outcome classificado + `error_type` +
  `resolution_note` em `apply_manual_correction`.
- `forza-db/.../schema_ddl.rs`: CHECKs de `review_cases` sem `'ignored'`
  (flags intacto).
- `forza-domain/.../enums.rs`: remover `ReviewCaseStatus::Ignored`,
  `ReviewOutcome::Ignored` + testes `VALUES` (`ImageFlagStatus::Ignored` fica).
- `forza-db/.../corrections.rs`: outcome classificado + `error_type` +
  `resolution_note` em `apply_manual_correction`.
- `forza-app/.../review_queue.rs`: remover `ignore_case`; `reopen_case`
  restringe mensagem (predicado `<> 'open'` já serve).
- `forza-gui/.../worker.rs`: remover `Request::IgnoreCase` + handler;
  outcome hardcoded sem `"ignored"`.
- `forza-gui/.../callbacks/review.rs`: remover botão/handler ignore;
  status model sem `"ignored"`.
- `forza-gui/ui/pages/review.slint`: idem no filtro.
- `forza-domain/.../enums.rs`: marcar `Ignored` como legado (atributo/depósito,
  sem remover — outros crates referenciam; remoção total é churn sem ganho).
- Testes: `review_upsert.rs` += reopen-on-return; novo `decide_outcome.rs`
  (confirm vs correct + error_type + note); `worker_round_trip` continua verde;
  doctor_full inalterado (vocab mantido de propósito).

## 5. Fora de escopo (não propor agora)

- Trocar `outcome` de auto_resolved no banco (proibido pelo CHECK; display
  mapping já resolve a leitura).
- N+1 `lap_best_where` (P4 conhecido).

## 6. Decisões (aprovadas e implementadas)

- [x] Remover `ignore` (recomendado: sim).
- [x] Reopen paridade D2 (recomendado: sim).
- [x] Outcome classificado + error_type (recomendado: sim).


