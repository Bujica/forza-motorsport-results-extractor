CREATE TABLE external_lap_records (
	id VARCHAR NOT NULL, 
	import_id VARCHAR NOT NULL, 
	track VARCHAR NOT NULL, 
	track_normalized VARCHAR, 
	race_class VARCHAR NOT NULL, 
	driver VARCHAR NOT NULL, 
	driver_normalized VARCHAR, 
	car VARCHAR NOT NULL, 
	car_normalized VARCHAR, 
	weather VARCHAR NOT NULL, 
	best_lap VARCHAR NOT NULL, 
	best_lap_ms INTEGER NOT NULL, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(import_id) REFERENCES external_record_imports (id) ON DELETE CASCADE
,
	CONSTRAINT ck_external_lap_records_weather_vocab CHECK (weather IN ('dry', 'rain', 'unknown')),
	CONSTRAINT ck_external_lap_records_best_lap_ms CHECK (best_lap_ms >= 0));

CREATE TABLE external_record_imports (
	id VARCHAR NOT NULL, 
	source_path VARCHAR NOT NULL, 
	source_hash VARCHAR, 
	status VARCHAR NOT NULL, 
	active BOOLEAN NOT NULL, 
	total_rows INTEGER DEFAULT 0 NOT NULL, 
	accepted_rows INTEGER DEFAULT 0 NOT NULL, 
	rejected_rows INTEGER DEFAULT 0 NOT NULL, 
	issue_count INTEGER DEFAULT 0 NOT NULL, 
	issues_json JSON, 
	created_at DATETIME NOT NULL, 
	imported_at DATETIME, 
	activated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_external_record_imports_total_rows CHECK (total_rows >= 0), 
	CONSTRAINT ck_external_record_imports_accepted_rows CHECK (accepted_rows >= 0), 
	CONSTRAINT ck_external_record_imports_rejected_rows CHECK (rejected_rows >= 0), 
	CONSTRAINT ck_external_record_imports_issue_count CHECK (issue_count >= 0)
,
	CONSTRAINT ck_external_record_imports_status_vocab CHECK (status IN ('pending', 'active', 'failed')));

CREATE INDEX idx_external_lap_records_active_order ON external_lap_records (track, race_class, best_lap_ms) WHERE active = 1;

CREATE TABLE lap_records (
	id VARCHAR NOT NULL, 
	run_id VARCHAR NOT NULL, 
	image_file_id VARCHAR NOT NULL, 
	extraction_result_id VARCHAR NOT NULL, 
	lap_index INTEGER NOT NULL,
	source_file VARCHAR DEFAULT '' NOT NULL, 
	driver VARCHAR DEFAULT '' NOT NULL, 
	driver_normalized VARCHAR DEFAULT '' NOT NULL, 
	car VARCHAR DEFAULT '' NOT NULL, 
	car_normalized VARCHAR DEFAULT '' NOT NULL, 
	race_class VARCHAR DEFAULT '' NOT NULL, 
	track VARCHAR DEFAULT '' NOT NULL, 
	track_normalized VARCHAR DEFAULT '' NOT NULL, 
	weather VARCHAR DEFAULT 'unknown' NOT NULL, 
	temp_f FLOAT, 
	temp_c FLOAT, 
	best_lap VARCHAR DEFAULT '' NOT NULL, 
	best_lap_ms INTEGER DEFAULT 0 NOT NULL, 
	dirty BOOLEAN DEFAULT 0 NOT NULL, 
	raw_lap_json JSON, 
	is_best_lap BOOLEAN DEFAULT 0 NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_lap_records_result_index UNIQUE (extraction_result_id, lap_index), 
	CONSTRAINT uq_lap_records_image_file_run_index UNIQUE (image_file_id, run_id, lap_index), 
	CONSTRAINT ck_lap_records_index CHECK (lap_index >= 0), 
	CONSTRAINT ck_lap_records_best_lap_ms CHECK (best_lap_ms >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT, 
	FOREIGN KEY(extraction_result_id) REFERENCES extraction_results (id) ON DELETE CASCADE
);

CREATE TABLE prompt_snapshots (
	id VARCHAR NOT NULL, 
	prompt_name VARCHAR NOT NULL, 
	version_label VARCHAR, 
	content_hash VARCHAR NOT NULL, 
	system_text VARCHAR NOT NULL, 
	user_text_template VARCHAR, 
	response_schema_json VARCHAR, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_prompt_snapshots_name_hash UNIQUE (prompt_name, content_hash)
);

CREATE TABLE reference_cars (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	normalized_name VARCHAR, 
	race_class VARCHAR, 
	aliases_json JSON, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE reference_tracks (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	normalized_name VARCHAR, 
	aliases_json JSON, 
	active BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

CREATE TABLE review_corrections (
            id VARCHAR NOT NULL,
            stable_key VARCHAR NOT NULL,
            image_file_id VARCHAR NOT NULL,
            lap_index INTEGER,
            field VARCHAR NOT NULL,
            model_value VARCHAR,
            corrected_value VARCHAR NOT NULL,
            error_type VARCHAR,
            cause VARCHAR DEFAULT 'unknown' NOT NULL,
            review_case_id VARCHAR,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            FOREIGN KEY(review_case_id) REFERENCES review_cases (id) ON DELETE SET NULL,
            FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT,
            CONSTRAINT ck_review_corrections_field_vocab CHECK (field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver')),
            CONSTRAINT ck_review_corrections_cause_vocab CHECK (cause IN ('review', 'rebuild', 'auto', 'unknown')),
            CONSTRAINT uq_review_corrections_stable_key UNIQUE (stable_key)
        );

CREATE TABLE image_files (
	id VARCHAR NOT NULL, 
	file_hash VARCHAR NOT NULL, 
	duplicate_of_image_file_id VARCHAR, 
	size_bytes INTEGER, 
	width_px INTEGER, 
	height_px INTEGER, 
	bit_depth INTEGER, 
	color_mode VARCHAR, 
	mime_type VARCHAR, 
	image_format VARCHAR, 
	image_metadata_json JSON, 
	current_name VARCHAR, 
	current_path VARCHAR, 
	semantic_name VARCHAR, 
	file_modified_at DATETIME, 
	race_datetime DATETIME, 
	race_date DATE, 
	race_datetime_source VARCHAR DEFAULT 'file_modified_at' NOT NULL, 
	file_status VARCHAR DEFAULT 'available' NOT NULL, 
	best_lap_status VARCHAR DEFAULT 'pending' NOT NULL, 
	first_seen_at DATETIME NOT NULL, 
	last_seen_at DATETIME, 
	missing_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_image_files_size_nonnegative CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	CONSTRAINT ck_image_files_width_positive CHECK (width_px IS NULL OR width_px > 0), 
	CONSTRAINT ck_image_files_height_positive CHECK (height_px IS NULL OR height_px > 0), 
	FOREIGN KEY(duplicate_of_image_file_id) REFERENCES image_files (id) ON DELETE SET NULL, 
	CONSTRAINT ck_image_files_file_status_vocab CHECK (file_status IN ('available', 'missing')),
	CONSTRAINT ck_image_files_best_lap_status_vocab CHECK (best_lap_status IN ('pending', 'contributing', 'non_contributing'))
);

CREATE INDEX idx_image_files_hash ON image_files (file_hash);

CREATE INDEX idx_image_files_duplicate_of ON image_files (duplicate_of_image_file_id);

CREATE INDEX idx_image_files_file_modified_at ON image_files (file_modified_at);

CREATE INDEX idx_image_files_best_lap_status ON image_files (best_lap_status);

CREATE INDEX idx_image_files_status ON image_files (file_status);

CREATE TABLE extraction_runs (
	id VARCHAR NOT NULL, 
	status VARCHAR DEFAULT 'pending' NOT NULL, 
	mode VARCHAR DEFAULT 'normal' NOT NULL, 
	backend VARCHAR DEFAULT 'lmstudio' NOT NULL, 
	model VARCHAR NOT NULL, 
	prompt_snapshot_id VARCHAR, 
	prompt_name VARCHAR, 
	prompt_hash VARCHAR, 
	input_dir VARCHAR, 
	workers INTEGER DEFAULT 1 NOT NULL, 
	image_format VARCHAR, 
	max_width INTEGER, 
	encode_quality INTEGER, 
	grayscale BOOLEAN DEFAULT 0 NOT NULL, 
	context_length INTEGER, 
	reasoning_mode VARCHAR, 
	eval_batch_size INTEGER, 
	physical_batch_size INTEGER, 
	flash_attention BOOLEAN, 
	offload_kv_cache_to_gpu BOOLEAN, 
	max_completion_tokens INTEGER, 
	temperature FLOAT, 
	max_retries INTEGER, 
	timeout_connect INTEGER, 
	timeout_read INTEGER, 
	performance_tps_floor FLOAT, 
	performance_reload_elapsed_s FLOAT, 
	performance_reload_streak INTEGER, 
	config_extra_json VARCHAR, 
	total_inputs INTEGER DEFAULT 0 NOT NULL, 
	to_process INTEGER DEFAULT 0 NOT NULL, 
	processed INTEGER DEFAULT 0 NOT NULL, 
	succeeded INTEGER DEFAULT 0 NOT NULL, 
	failed INTEGER DEFAULT 0 NOT NULL, 
	skipped INTEGER DEFAULT 0 NOT NULL, 
	duplicate_count INTEGER DEFAULT 0 NOT NULL, 
	review_case_count INTEGER DEFAULT 0 NOT NULL, 
	operational_error_code VARCHAR, 
	operational_error_message VARCHAR, 
	created_at DATETIME NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_extraction_runs_workers CHECK (workers >= 1), 
	CONSTRAINT ck_extraction_runs_total_inputs CHECK (total_inputs >= 0), 
	CONSTRAINT ck_extraction_runs_to_process CHECK (to_process >= 0), 
	CONSTRAINT ck_extraction_runs_processed CHECK (processed >= 0), 
	CONSTRAINT ck_extraction_runs_succeeded CHECK (succeeded >= 0), 
	CONSTRAINT ck_extraction_runs_failed CHECK (failed >= 0), 
	CONSTRAINT ck_extraction_runs_skipped CHECK (skipped >= 0), 
	CONSTRAINT ck_extraction_runs_duplicate_count CHECK (duplicate_count >= 0), 
	FOREIGN KEY(prompt_snapshot_id) REFERENCES prompt_snapshots (id) ON DELETE RESTRICT
,
	CONSTRAINT ck_extraction_runs_status_vocab CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
	CONSTRAINT ck_extraction_runs_mode_vocab CHECK (mode IN ('normal', 'dry_run'))
);

CREATE TABLE run_inputs (
	id INTEGER NOT NULL, 
	run_id VARCHAR NOT NULL, 
	image_file_id VARCHAR, 
	input_order INTEGER NOT NULL, 
	input_path VARCHAR NOT NULL, 
	normalized_path VARCHAR, 
	file_name VARCHAR, 
	extension VARCHAR, 
	file_hash VARCHAR, 
	size_bytes INTEGER, 
	mtime_ns INTEGER, 
	decision VARCHAR NOT NULL, 
	process_reason VARCHAR, 
	skip_reason VARCHAR, 
	duplicate_kind VARCHAR, 
	duplicate_of_hash VARCHAR, 
	duplicate_of_input_id INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_run_inputs_order CHECK (input_order >= 0), 
	CONSTRAINT ck_run_inputs_size_nonnegative CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE SET NULL, 
	FOREIGN KEY(duplicate_of_input_id) REFERENCES run_inputs (id) ON DELETE SET NULL
,
	CONSTRAINT ck_run_inputs_decision_vocab CHECK (decision IN ('process', 'skip', 'duplicate', 'missing', 'unsupported', 'outside_input', 'hash_failed')),
	CONSTRAINT ck_run_inputs_duplicate_kind_vocab CHECK (duplicate_kind IS NULL OR duplicate_kind IN ('hash', 'batch'))
);

CREATE TABLE extraction_results (
	id VARCHAR NOT NULL, 
	run_id VARCHAR NOT NULL, 
	run_input_id INTEGER NOT NULL, 
	image_file_id VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	error_type VARCHAR, 
	error_message VARCHAR, 
	accepted_attempt_id VARCHAR, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	model VARCHAR, 
	model_instance_id VARCHAR, 
	prompt_snapshot_id VARCHAR, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	reasoning_tokens INTEGER, 
	total_tokens INTEGER, 
	tokens_per_second FLOAT, 
	time_to_first_token_s FLOAT, 
	model_load_time_s FLOAT, 
	request_image_format VARCHAR, 
	request_image_mime_type VARCHAR, 
	request_image_width INTEGER, 
	request_image_height INTEGER, 
	request_image_bytes INTEGER, 
	duration_ms INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_extraction_results_run_image UNIQUE (run_id, image_file_id), 
	CONSTRAINT uq_extraction_results_run_input UNIQUE (run_input_id), 
	CONSTRAINT ck_extraction_results_attempt_count CHECK (attempt_count >= 0), 
	CONSTRAINT ck_extraction_results_image_width CHECK (request_image_width IS NULL OR request_image_width > 0), 
	CONSTRAINT ck_extraction_results_image_height CHECK (request_image_height IS NULL OR request_image_height > 0), 
	CONSTRAINT ck_extraction_results_image_bytes CHECK (request_image_bytes IS NULL OR request_image_bytes >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_input_id) REFERENCES run_inputs (id) ON DELETE CASCADE, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT, 
	FOREIGN KEY(accepted_attempt_id) REFERENCES extraction_attempts (id) ON DELETE RESTRICT, 
	FOREIGN KEY(prompt_snapshot_id) REFERENCES prompt_snapshots (id) ON DELETE RESTRICT
,
	CONSTRAINT ck_extraction_results_status_vocab CHECK (status IN ('pending', 'running', 'ok', 'error', 'cancelled'))
);

CREATE TABLE extraction_attempts (
	id VARCHAR NOT NULL, 
	extraction_result_id VARCHAR NOT NULL, 
	run_id VARCHAR NOT NULL, 
	image_file_id VARCHAR NOT NULL, 
	runtime_snapshot_id VARCHAR, 
	attempt_number INTEGER NOT NULL, 
	attempt_reason VARCHAR NOT NULL, 
	status VARCHAR NOT NULL, 
	accepted BOOLEAN DEFAULT 0 NOT NULL, 
	rejected_reason VARCHAR, 
	http_status INTEGER, 
	error_code VARCHAR, 
	error_message VARCHAR, 
	model VARCHAR, 
	model_instance_id VARCHAR, 
	request_image_format VARCHAR, 
	request_image_mime_type VARCHAR, 
	request_image_width INTEGER, 
	request_image_height INTEGER, 
	request_image_bytes INTEGER, 
	context_length INTEGER, 
	reasoning_mode VARCHAR, 
	request_config_json JSON, 
	request_messages_json JSON, 
	request_hash VARCHAR, 
	retry_instruction_text VARCHAR, 
	raw_response VARCHAR, 
	parsed_json JSON, 
	parse_error VARCHAR, 
	validation_status VARCHAR, 
	validation_issues_json JSON, 
	response_stats_json JSON, 
	model_load_config_json JSON, 
	input_tokens INTEGER, 
	output_tokens INTEGER, 
	reasoning_tokens INTEGER, 
	total_tokens INTEGER, 
	time_to_first_token_s FLOAT, 
	duration_ms INTEGER, 
	tokens_per_second FLOAT, 
	model_load_time_s FLOAT, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_extraction_attempts_result_attempt UNIQUE (extraction_result_id, attempt_number), 
	CONSTRAINT ck_attempt_acceptance_status CHECK ((accepted = 1 AND status = 'ok') OR (accepted = 0 AND status <> 'ok')), 
	CONSTRAINT ck_attempt_number_positive CHECK (attempt_number >= 1), 
	CONSTRAINT ck_attempt_image_width CHECK (request_image_width IS NULL OR request_image_width > 0), 
	CONSTRAINT ck_attempt_image_height CHECK (request_image_height IS NULL OR request_image_height > 0), 
	CONSTRAINT ck_attempt_image_bytes CHECK (request_image_bytes IS NULL OR request_image_bytes >= 0), 
	FOREIGN KEY(extraction_result_id) REFERENCES extraction_results (id) ON DELETE CASCADE, 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT, 
	FOREIGN KEY(runtime_snapshot_id) REFERENCES model_runtime_snapshots (id) ON DELETE SET NULL
,
	CONSTRAINT ck_extraction_attempts_status_vocab CHECK (status IN ('ok', 'error', 'cancelled'))
);

CREATE TABLE model_artifacts (
	id VARCHAR NOT NULL, 
	run_id VARCHAR NOT NULL, 
	image_file_id VARCHAR, 
	extraction_result_id VARCHAR, 
	attempt_id VARCHAR, 
	artifact_type VARCHAR NOT NULL, 
	file_path VARCHAR NOT NULL, 
	relative_path VARCHAR, 
	sha256 VARCHAR NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	media_type VARCHAR, 
	is_canonical BOOLEAN DEFAULT 0 NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_model_artifacts_size_nonnegative CHECK (size_bytes >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE SET NULL, 
	FOREIGN KEY(extraction_result_id) REFERENCES extraction_results (id) ON DELETE CASCADE, 
	FOREIGN KEY(attempt_id) REFERENCES extraction_attempts (id) ON DELETE CASCADE
);

CREATE TABLE review_cases (
	id VARCHAR NOT NULL, 
	run_id VARCHAR, 
	image_file_id VARCHAR, 
	extraction_result_id VARCHAR, 
	lap_record_id VARCHAR, 
	status VARCHAR DEFAULT 'open' NOT NULL, 
	reason VARCHAR NOT NULL, 
	business_key VARCHAR NOT NULL, 
	driver VARCHAR, 
	driver_normalized VARCHAR, 
	track VARCHAR, 
	track_normalized VARCHAR, 
	race_class VARCHAR, 
	car VARCHAR, 
	car_normalized VARCHAR, 
	lap_index INTEGER, 
	best_lap VARCHAR, 
	message VARCHAR, 
	track_suggestions_json JSON, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME, 
	resolved_at DATETIME, 
	resolution_note VARCHAR, "trigger" VARCHAR, outcome VARCHAR DEFAULT 'pending' NOT NULL, decision_field VARCHAR, model_value VARCHAR, corrected_value VARCHAR, error_type VARCHAR, case_number INTEGER DEFAULT 0 NOT NULL, source_file VARCHAR DEFAULT '' NOT NULL, weather VARCHAR DEFAULT 'unknown' NOT NULL, temp_f FLOAT, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_review_cases_business_key UNIQUE (business_key), 
	CONSTRAINT uq_review_cases_case_number UNIQUE (case_number), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE SET NULL, 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT, 
	FOREIGN KEY(extraction_result_id) REFERENCES extraction_results (id) ON DELETE SET NULL, 
	FOREIGN KEY(lap_record_id) REFERENCES lap_records (id) ON DELETE SET NULL
,
	CONSTRAINT ck_review_cases_status_vocab CHECK (status IN ('open', 'resolved', 'ignored', 'auto_resolved')),
	CONSTRAINT ck_review_cases_outcome_vocab CHECK (outcome IN ('pending', 'confirmed', 'model_error', 'ignored')),
	CONSTRAINT ck_review_cases_reason_vocab CHECK (reason IN ('dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name')),
	CONSTRAINT ck_review_cases_trigger_vocab CHECK ("trigger" IS NULL OR "trigger" IN ('model_marked_dirty', 'weather_unknown', 'rain_time_suspicious', 'track_unknown', 'track_unresolved', 'track_not_in_reference', 'class_unknown', 'class_invalid', 'car_empty', 'car_not_in_reference', 'driver_name_empty', 'numeric_prefix', 'invalid_symbol')),
	CONSTRAINT ck_review_cases_decision_field_vocab CHECK (decision_field IS NULL OR decision_field IN ('dirty', 'track', 'weather', 'race_class', 'car', 'driver'))
);

CREATE TABLE image_flags (
	id VARCHAR NOT NULL, 
	image_file_id VARCHAR NOT NULL, 
	run_id VARCHAR, 
	extraction_result_id VARCHAR, 
	lap_record_id VARCHAR, 
	flag_key VARCHAR NOT NULL, 
	flag_scope VARCHAR DEFAULT 'image' NOT NULL, 
	lap_index INTEGER, 
	driver_normalized VARCHAR, 
	track_normalized VARCHAR, 
	race_class VARCHAR, 
	flag_type VARCHAR NOT NULL, 
	status VARCHAR DEFAULT 'active' NOT NULL, 
	created_by VARCHAR DEFAULT 'system' NOT NULL, 
	reason VARCHAR, 
	note VARCHAR, 
	created_at DATETIME NOT NULL, 
	resolved_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_image_flags_flag_key UNIQUE (flag_key), 
	FOREIGN KEY(image_file_id) REFERENCES image_files (id) ON DELETE RESTRICT, 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE SET NULL, 
	FOREIGN KEY(extraction_result_id) REFERENCES extraction_results (id) ON DELETE SET NULL, 
	FOREIGN KEY(lap_record_id) REFERENCES lap_records (id) ON DELETE SET NULL
,
	CONSTRAINT ck_image_flags_status_vocab CHECK (status IN ('active', 'resolved', 'ignored')),
	CONSTRAINT ck_image_flags_scope_vocab CHECK (flag_scope IN ('image', 'lap')),
	CONSTRAINT ck_image_flags_flag_type_vocab CHECK (flag_type IN ('duplicate', 'dirty_lap', 'track', 'weather', 'race_class', 'car', 'driver_name'))
);

CREATE TABLE export_artifacts (
	id VARCHAR NOT NULL, 
	run_id VARCHAR, 
	artifact_type VARCHAR NOT NULL, 
	file_path VARCHAR NOT NULL, 
	relative_path VARCHAR, 
	sha256 VARCHAR, 
	size_bytes INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_export_artifacts_size_nonnegative CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE SET NULL
);

CREATE INDEX idx_lap_records_best_track_class_car ON lap_records (track_normalized, race_class, car_normalized) WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_best_track_class_driver ON lap_records (track_normalized, race_class, driver_normalized) WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_best_gui_order ON lap_records (track, race_class, weather, best_lap_ms, driver, car) WHERE is_best_lap = 1;

CREATE INDEX idx_lap_records_image_file ON lap_records (image_file_id);

CREATE INDEX idx_lap_records_track_class_car ON lap_records (track_normalized, race_class, car_normalized);

CREATE INDEX idx_lap_records_track_class_driver ON lap_records (track_normalized, race_class, driver_normalized);

CREATE TABLE model_runtime_snapshots (
	id VARCHAR NOT NULL, 
	run_id VARCHAR NOT NULL, 
	snapshot_kind VARCHAR DEFAULT 'preflight' NOT NULL, 
	endpoint VARCHAR NOT NULL, 
	configured_model VARCHAR, 
	matched_model VARCHAR, 
	loaded_model VARCHAR, 
	instance_id VARCHAR, 
	display_name VARCHAR, 
	publisher VARCHAR, 
	architecture VARCHAR, 
	format VARCHAR, 
	params_string VARCHAR, 
	quantization VARCHAR, 
	selected_variant VARCHAR, 
	size_bytes INTEGER, 
	max_context_length INTEGER, 
	capabilities_json JSON, 
	desired_load_config_json JSON, 
	effective_load_config_json JSON, 
	load_time_seconds FLOAT, 
	health_ok BOOLEAN DEFAULT 0 NOT NULL, 
	health_message VARCHAR, 
	model_matches_config BOOLEAN, 
	captured_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_runtime_size_nonnegative CHECK (size_bytes IS NULL OR size_bytes >= 0), 
	FOREIGN KEY(run_id) REFERENCES extraction_runs (id) ON DELETE CASCADE
);

CREATE INDEX idx_model_runtime_run_kind ON model_runtime_snapshots (run_id, snapshot_kind);

CREATE UNIQUE INDEX idx_runtime_one_preflight_per_run ON model_runtime_snapshots (run_id) WHERE snapshot_kind = 'preflight';

CREATE INDEX idx_review_corrections_image_file_field ON review_corrections (image_file_id, field);




CREATE INDEX idx_extraction_runs_created ON extraction_runs (created_at);

CREATE INDEX idx_extraction_runs_status ON extraction_runs (status);

CREATE INDEX idx_run_inputs_hash ON run_inputs (file_hash);

CREATE INDEX idx_run_inputs_process_reason ON run_inputs (run_id, process_reason);

CREATE INDEX idx_run_inputs_run_decision ON run_inputs (run_id, decision);

CREATE INDEX idx_run_inputs_image_file ON run_inputs (image_file_id);

CREATE INDEX idx_extraction_results_image_file ON extraction_results (image_file_id);

CREATE INDEX idx_extraction_results_status ON extraction_results (status);

CREATE UNIQUE INDEX idx_attempts_one_accepted_per_result ON extraction_attempts (extraction_result_id) WHERE accepted = 1;

CREATE INDEX idx_attempts_reason ON extraction_attempts (attempt_reason);

CREATE INDEX idx_attempts_run_status ON extraction_attempts (run_id, status);

CREATE INDEX idx_model_artifacts_attempt ON model_artifacts (attempt_id);

CREATE INDEX idx_model_artifacts_run_image_file ON model_artifacts (run_id, image_file_id);

CREATE INDEX idx_review_cases_outcome ON review_cases (outcome);

CREATE INDEX idx_review_cases_reason_trigger ON review_cases (reason, "trigger");

CREATE INDEX idx_review_cases_status_reason ON review_cases (status, reason);

CREATE INDEX idx_image_flags_image_file_type_status ON image_flags (image_file_id, flag_type, status);

