from pathlib import Path

from forza.pipeline.image import (
    ExistingImage,
    file_hash,
    log_duplicate_skips,
    plan_images,
    semantic_filename,
)


def test_semantic_filename_uses_track_class_and_suffix():
    assert semantic_filename("Track/Invalid", "A", " - run-1.png") == "TrackInvalid - A - run-1.png"


def test_plan_images_tracks_new_existing_and_duplicate_without_moving(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.png"
    cached = input_dir / "cached.png"
    duplicate = input_dir / "duplicate.png"
    already_seen_path = input_dir / "already_seen.png"
    first.write_bytes(b"new image")
    cached.write_bytes(b"cached image")
    duplicate.write_bytes(b"new image")
    already_seen_path.write_bytes(b"already imported")

    plan = plan_images(
        [first, cached, duplicate, already_seen_path],
        {file_hash(cached), file_hash(already_seen_path)},
        known_paths={str(already_seen_path)},
        force=False,
    )

    assert plan.process_count == 1
    assert plan.duplicate_count == 2
    assert plan.existing_images == [
        ExistingImage(path=already_seen_path, file_hash=file_hash(already_seen_path))
    ]
    assert [item.path for item in plan.duplicates] == [cached, duplicate]
    assert all(path.exists() for path in (first, cached, duplicate, already_seen_path))


def test_plan_images_rehashes_known_paths_before_marking_existing(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    replaced = input_dir / "same_name.png"
    replaced.write_bytes(b"new file contents")

    plan = plan_images(
        [replaced],
        {"old-hash_1"},
        known_paths={str(replaced): "old-hash_1"},
        force=False,
    )

    assert plan.existing_images == []
    assert [item.path for item in plan.new_images] == [replaced]


def test_force_reprocesses_known_hashes_but_not_batch_duplicates(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.png"
    duplicate = input_dir / "duplicate.png"
    first.write_bytes(b"same")
    duplicate.write_bytes(b"same")

    plan = plan_images([first, duplicate], {file_hash(first)}, force=True)

    assert [item.path for item in plan.new_images] == [first]
    assert [item.path for item in plan.duplicates] == [duplicate]


def test_duplicate_skip_is_non_mutating(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    first = input_dir / "first.png"
    duplicate = input_dir / "duplicate.png"
    first.write_bytes(b"same")
    duplicate.write_bytes(b"same")

    plan = plan_images([first, duplicate], set())
    skipped = log_duplicate_skips(plan)

    assert skipped == [duplicate]
    assert first.exists()
    assert duplicate.exists()

