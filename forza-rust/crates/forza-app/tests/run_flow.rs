// Fase 8 e2e harness: unwraps are idiomatic assertion helpers here.
#![allow(clippy::unwrap_used, clippy::expect_used, dead_code)]

//! Fase 8 criterion end-to-end on a test database:
//! processar (replay) → revisar → corrigir → rebuild, sem nova chamada ao
//! modelo.

use rusqlite::Connection;

use forza_app::services::extraction_replay::replay_recorded_response;
use forza_db::repositories::corrections::apply_manual_correction;
use forza_db::repositories::{
    RunInsert, images as img_repo, insert_run, mark_best_laps, query_review_candidates,
    upsert_review_cases,
};
use forza_db::upgrade;

fn raw_response(track: &str, driver: &str, car: &str, class: &str, bl: &str) -> String {
    format!(
        r#"{{"t":"{track}","tf":80,"w":"dry","e":[{{"dr":"{driver}","ca":"{car}","cl":"{class}","bl":"{bl}"}}]}}"#
    )
}

struct Scene {
    guard: tempfile::TempDir,
    conn: Connection,
    run_id: String,
}

fn scene() -> Scene {
    let guard = tempfile::tempdir().unwrap();
    let db = guard.path().join("fase8.sqlite3");
    upgrade(&db).unwrap();
    let conn = forza_db::open_connection(&db).unwrap();

    let run_id = insert_run(
        &conn,
        &RunInsert {
            id: "20260825_120000_fase8".into(),
            status: "running".into(),
            mode: "normal".into(),
        },
    )
    .unwrap();

    for (idx, image_id) in ["img-player", "img-rival", "img-dirty"].iter().enumerate() {
        img_repo::insert_image_file(
            &conn,
            &img_repo::ImageFileInsert {
                id: image_id,
                file_hash: &format!("hash-{idx}"),
                current_name: &format!("shot_{idx}.png"),
                current_path: &format!(r"C:\shots\shot_{idx}.png"),
                size_bytes: 1000 + idx as i64,
                width_px: 3840,
                height_px: 2160,
            },
        )
        .unwrap();
    }

    Scene {
        guard,
        conn,
        run_id,
    }
}

fn replay(conn: &mut Connection, image: &str, seq: i64, body: &str) {
    let run_id = "20260825_120000_fase8";
    let result_id = forza_db::repositories::runs::insert_input_and_result(
        conn, run_id, image, "process", "running", seq,
    )
    .unwrap();
    replay_recorded_response(conn, run_id, image, &result_id, body, "test-model").unwrap();
}

#[test]
fn processar_revisar_corrigir_rebuild_sem_modelo() {
    let mut scene = scene();
    let conn = &mut scene.conn;
    #[allow(clippy::needless_borrow)]
    // ── 1. PROCESSAR (replay de respostas gravadas/sintéticas) ────────────
    let player_clean = raw_response(
        "Fuji Speedway",
        "Bujica89",
        "Audi R8 LMS",
        "692 A",
        "1:30.000",
    );
    let rival_fast = raw_response(
        "Fuji Speedway",
        "Rival One",
        "BMW M4 GT3",
        "692 A",
        "1:29.000",
    );
    let player_dirty = raw_response(
        "Fuji Speedway",
        "Bujica89",
        "Audi R8 LMS",
        "692 A",
        "1:28.000 ▲",
    );

    replay(conn, "img-player", 1, &player_clean);
    replay(conn, "img-rival", 2, &rival_fast);
    replay(conn, "img-dirty", 3, &player_dirty);

    // ── 2. BEST-LAPS: dirty lap do player define a fronteira ──────────────
    let winners = mark_best_laps(conn, Some("bujica89")).unwrap();
    assert_eq!(winners.len(), 1, "{winners:?}");
    let winner_dirty: i64 = conn
        .query_row(
            "SELECT dirty FROM lap_records WHERE id=?1",
            rusqlite::params![winners[0]],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(
        winner_dirty, 1,
        "fronteira vencida pela volta suja (semântica Python)"
    );

    // ── 3. REVISAR: caso dirty_lap gerado porque suja+best afeta output ───
    let candidates = query_review_candidates(conn).unwrap();
    assert!(
        candidates.iter().any(|c| c.reason == "dirty_lap"),
        "esperava candidato dirty_lap"
    );
    let (inserted, _kept, _auto) = upsert_review_cases(conn, &candidates).unwrap();
    assert!(inserted >= 1);
    let open_case: i64 = conn
        .query_row(
            "SELECT COUNT(*) FROM review_cases WHERE reason='dirty_lap' AND status='open'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(open_case, 1);

    // ── 4. CORRIGIR: operador marca a volta como não-suja ─────────────────
    let case_number: i64 = conn
        .query_row(
            "SELECT case_number FROM review_cases WHERE reason='dirty_lap' AND status='open'",
            [],
            |r| r.get(0),
        )
        .unwrap();
    let lap_id = apply_manual_correction(conn, case_number, "dirty", "false", None).unwrap();

    let still_dirty: i64 = conn
        .query_row(
            "SELECT dirty FROM lap_records WHERE id=?1",
            rusqlite::params![lap_id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(still_dirty, 0);

    let resolved: String = conn
        .query_row(
            "SELECT status FROM review_cases WHERE case_number=?1",
            rusqlite::params![case_number],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(resolved, "resolved");

    // ── 5. REBUILD: recomputa tudo SEM chamar o modelo ─────────────────────
    let outcome = forza_app::services::rebuild::rebuild(conn, "bujica89").unwrap();

    // A volta corrigida (88s, agora LIMPA) continua sendo a fronteira
    // legítima — corrigir dirty não altera tempos. O rival 89s continua
    // abaixo do limite do player e por isso NÃO aparece (Python semantics).
    let best_ids: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT id FROM lap_records WHERE is_best_lap=1 ORDER BY id")
            .unwrap();
        stmt.query_map([], |r| r.get(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    };
    assert_eq!(best_ids.len(), 1, "{best_ids:?}");
    assert_eq!(best_ids[0], lap_id);

    // Caso antigo permanece resolvido; nenhum novo dirty_lap é criado.
    let dirty_cases: Vec<String> = {
        let mut stmt = conn
            .prepare("SELECT status FROM review_cases WHERE reason='dirty_lap'")
            .unwrap();
        stmt.query_map([], |r| r.get::<_, String>(0))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap()
    };
    assert!(dirty_cases.iter().all(|s| s != "open"), "{dirty_cases:?}");

    assert_eq!(outcome.best_lap_winners, 1);

    // Doctor continua saudável após todo o fluxo.
    let report =
        forza_db::doctor::doctor_on_path(&scene.guard.path().join("fase8.sqlite3")).unwrap();
    assert!(report.ok, "{report:?}");
}
