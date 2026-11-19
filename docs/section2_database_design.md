# Section 2 — Database Design

## Bronze Layer - Preserve Raw Data and Add Metadata

### Purpose

The Bronze layer ingests source data with minimal transformation, preserving the original values and ingestion context as well as metadata. It serves as the replayable source of truth for Silver transformations, including records that may later fail business validation.

### Proposed Tables

| Table | Grain | Record Identity | Purpose |
| --- | --- | --- | --- |
| `bronze_enrollments` | One row per source CSV row per ingestion batch | (`batch_id`, `source_row_number`) | Preserve raw enrollment records, including duplicates and invalid values. |
| `bronze_courses` | One row per source course row per ingestion batch | (`batch_id`, `source_row_number`) | Preserve course master data and the original prerequisite JSON. |

### Table Schemas

**`bronze_enrollments`**

| Column | Type | Description |
| --- | --- | --- |
| `batch_id` | TEXT | Identifier for a logical ingestion batch. |
| `source_row_number` | INTEGER | Position of the record in its source batch; together with `batch_id`, identifies a raw row. |
| `source_file` | TEXT | Original filename or source identifier. |
| `ingested_at` | TIMESTAMP | Timestamp when the batch was ingested. |
| `enrollment_id` | TEXT | Raw enrollment identifier; not unique in Bronze. |
| `participant_id` | TEXT | Raw participant identifier. |
| `participant_name` | TEXT | Raw participant name. |
| `course_id` | TEXT | Raw course identifier. |
| `course_date` | TEXT | Original date representation, without parsing. |
| `amount` | TEXT | Original amount representation. |
| `subsidy` | TEXT | Original subsidy representation. |
| `credits_used` | TEXT | Original credits representation. |

**`bronze_courses`**

| Column | Type | Description |
| --- | --- | --- |
| `batch_id` | TEXT | Identifier for a logical ingestion batch. |
| `source_row_number` | INTEGER | Position of the course record within the batch. |
| `source_file` | TEXT | Source database/table or extract identifier. |
| `ingested_at` | TIMESTAMP | Timestamp when the batch was ingested. |
| `course_id` | TEXT | Original course identifier. |
| `name` | TEXT | Original course name. |
| `description` | TEXT | Original course description. |
| `prerequisites` | TEXT | Original JSON array, preserved without normalization. |

Source business fields are represented as `TEXT` in this logical design to avoid losing malformed values during ingestion. Silver converts them to the validated target types.

### Ingestion and Data Quality Rules

1. **Preserve raw values:** Do not standardize dates, cast monetary fields, deduplicate business IDs, or expand prerequisite arrays in Bronze.
2. **Add metadata:** Record `batch_id`, `source_file`, `source_row_number`, and `ingested_at` for traceability and replay.
3. **Basic ingestion checks:** Verify source readability and required structural columns. Record file/row counts and surface schema drift; preserve parseable records even when business values are invalid.
4. **Idempotent ingestion:** Reprocessing the same logical batch must not duplicate Bronze rows. Use a stable batch identity and unique (`batch_id`, `source_row_number`) within the batch; a corrected source version should receive a distinct batch identity.
5. **Retain history:** Allow the same `enrollment_id` or `course_id` to appear across batches. Resolve duplicates and conflicting versions in Silver, not Bronze.

### Design Rationale

Bronze does not enforce foreign keys to Silver tables. Raw records may reference unknown courses or contain invalid values, and preserving them is necessary for investigation and reprocessing. The Silver layer consumes Bronze data, validates it, and produces the cleaned relational model described below.

## Silver Layer — Cleaned and Normalized Data

### Purpose

The Silver layer transforms raw Bronze records into validated, standardized, and reusable relational datasets. It separates participant and course master data from enrollment transactions, and normalizes course prerequisites for easier querying and integrity checks.

The following is a proposed **logical target model**, not a change to the existing SQLite schema used in Section 1.

### Proposed Tables

| Table | Grain | Primary Key | Purpose |
| --- | --- | --- | --- |
| `silver_participants` | One row per participant | `participant_id` | Maintain a consistent participant reference. |
| `silver_courses` | One row per course | `course_id` | Maintain validated course attributes. |
| `silver_enrollments` | One row per enrollment record | `enrollment_id` | Store enrollment events and financial amounts. |
| `silver_course_prerequisites` | One row per course–prerequisite pair | (`course_id`, `prerequisite_course_id`) | Normalize the JSON prerequisite array into relational rows. |

### Table Schemas and Relationships

**`silver_participants`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `participant_id` | TEXT | Primary key; sourced from enrollment data. |
| `participant_name` | TEXT | Standardized participant name; conflicts require a defined resolution rule. |

**`silver_courses`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `course_id` | INTEGER | Primary key. |
| `name` | TEXT | Course name. |
| `description` | TEXT | Course description. |

The raw `prerequisites` JSON is retained in Bronze; its individual relationships are represented in `silver_course_prerequisites`.

**`silver_enrollments`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `enrollment_id` | INTEGER | Primary key. |
| `participant_id` | TEXT | Foreign key → `silver_participants.participant_id`. |
| `course_id` | INTEGER | Foreign key → `silver_courses.course_id`. |
| `course_date` | DATE | Standardized ISO date. |
| `amount` | DECIMAL(12,2) | Course amount; non-negative. |
| `subsidy` | DECIMAL(12,2) | Subsidy amount; non-negative. |
| `credits_used` | DECIMAL(12,2) | Credits used; non-negative. |

An enrollment is uniquely identified by `enrollment_id`, **not** by (`participant_id`, `course_id`): a participant may enroll in the same course more than once.

**`silver_course_prerequisites`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `course_id` | INTEGER | Composite primary key; foreign key → `silver_courses.course_id`. |
| `prerequisite_course_id` | INTEGER | Composite primary key; foreign key → `silver_courses.course_id`. |

Both columns reference the course master table. For example, a Bronze prerequisite array `[101, 102]` for course `103` becomes two rows: `(103, 101)` and `(103, 102)`.

### Transformation and Data Quality Rules

1. **Standardization:** Parse source dates into ISO format; convert IDs and monetary fields to appropriate types; normalize text whitespace without silently changing business meaning.
2. **Deduplication:** Use `enrollment_id` as the enrollment business key. If the same ID arrives with different values, flag the conflict and apply an explicitly defined source-of-truth or latest-version policy; do not arbitrarily keep one record.
3. **Referential integrity:** Check that each enrollment references a known course and participant. Check that prerequisite course IDs exist in the course master; quarantine invalid references for review.
4. **Financial validation:** Reject nonnumeric, nonfinite, or negative financial values. Under the stated assumption that subsidies and credits cannot exceed the course fee in combination, check `subsidy + credits_used <= amount`; confirm this rule with business stakeholders before production enforcement.
5. **Participant master:** Derive unique participants from enrollment records. If a participant ID has conflicting names, flag the issue rather than choosing an arbitrary value.
6. **Prerequisite validation:** Parse the JSON array, remove duplicate pairs, disallow self-prerequisites, and flag circular dependencies if the business rules prohibit them.
7. **Error handling:** Quarantine records that fail required checks, preserving the raw record reference, reason, and batch metadata for investigation and replay.

### Design Decisions and Assumptions

- **Section 1 remains unchanged:** it loads validated CSV data into the provided SQLite `enrollments` table. The Silver model is a future-state logical design.
- **No completion inference:** an enrollment indicates registration, not course completion. A separate completion/status source is required to determine whether prerequisites have actually been completed.
- **Metadata and lineage:** operational metadata such as source batch IDs can be retained as technical columns or managed through a separate lineage mapping; it does not need to be part of every business key.
- **Currency and precision:** `DECIMAL(12,2)` is an illustrative financial type. The source system's currency, precision, and rounding requirements must be confirmed.
- **Change handling:** course and participant master updates require a documented policy (e.g., current-state upsert or historical versioning), depending on reporting requirements.

## Silver Layer — Cleaned and Normalized Data

### Purpose

The Silver layer transforms raw Bronze records into validated, standardized, and reusable relational datasets. It separates participant and course master data from enrollment transactions, and normalizes course prerequisites for easier querying and integrity checks.

### Proposed Tables

| Table | Grain | Primary Key | Purpose |
| --- | --- | --- | --- |
| `silver_participants` | One row per participant | `participant_id` | Maintain a consistent participant reference. |
| `silver_courses` | One row per course | `course_id` | Maintain validated course attributes. |
| `silver_enrollments` | One row per enrollment record | `enrollment_id` | Store enrollment events and financial amounts. |
| `silver_course_prerequisites` | One row per course–prerequisite pair | (`course_id`, `prerequisite_course_id`) | Normalize the JSON prerequisite array into relational rows. |

### Table Schemas and Relationships

**`silver_participants`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `participant_id` | TEXT | Primary key; sourced from enrollment data. |
| `participant_name` | TEXT | Standardized participant name; conflicts require a defined resolution rule. |

**`silver_courses`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `course_id` | INTEGER | Primary key. |
| `course_name` | TEXT | Course name. |
| `description` | TEXT | Course description. |

The raw `prerequisites` JSON is retained in Bronze; its individual relationships are represented in `silver_course_prerequisites`.

**`silver_enrollments`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `enrollment_id` | INTEGER | Primary key. |
| `participant_id` | TEXT | Foreign key → `silver_participants.participant_id`. |
| `course_id` | INTEGER | Foreign key → `silver_courses.course_id`. |
| `course_date` | DATE | Standardized ISO date. |
| `amount` | DECIMAL(12,2) | Course amount; non-negative. |
| `subsidy` | DECIMAL(12,2) | Subsidy amount; non-negative. |
| `credits_used` | DECIMAL(12,2) | Credits used; non-negative. |

An enrollment is uniquely identified by `enrollment_id`, **not** by (`participant_id`, `course_id`): a participant may enroll in the same course more than once.

**`silver_course_prerequisites`**

| Column | Type | Constraint / Description |
| --- | --- | --- |
| `course_id` | INTEGER | Composite primary key; foreign key → `silver_courses.course_id`. |
| `prerequisite_course_id` | INTEGER | Composite primary key; foreign key → `silver_courses.course_id`. |

Both columns reference the course master table. For example, a Bronze prerequisite array `[101, 102]` for course `103` becomes two rows: `(103, 101)` and `(103, 102)`.

### Transformation and Data Quality Rules

1. **Standardization:** Parse source dates into ISO format; convert IDs and monetary fields to appropriate types; normalize text whitespace without silently changing business meaning.
2. **Deduplication:** Use `enrollment_id` as the enrollment business key. If the same ID arrives with different values, flag the conflict and apply an explicitly defined source-of-truth or latest-version policy; do not arbitrarily keep one record.
3. **Referential integrity:** Check that each enrollment references a known course and participant. Check that prerequisite course IDs exist in the course master; quarantine invalid references for review.
4. **Financial validation:** Reject nonnumeric, nonfinite, or negative financial values. Under the stated assumption that subsidies and credits cannot exceed the course fee in combination, check `subsidy + credits_used <= amount`; confirm this rule with business stakeholders before production enforcement.
5. **Participant master:** Derive unique participants from enrollment records. If a participant ID has conflicting names, flag the issue rather than choosing an arbitrary value.
6. **Prerequisite validation:** Parse the JSON array, remove duplicate pairs, disallow self-prerequisites, and flag circular dependencies if the business rules prohibit them.
7. **Error handling:** Quarantine records that fail required checks, preserving the raw record reference, reason, and batch metadata for investigation and replay.

### Design Decisions and Assumptions

- **Enrollment vs. Completion:** Enrollment records represent registrations, not confirmed course completions. Completion status would require an additional data source.
- **Financial Validation:** Subsidies and credits are assumed not to exceed the course amount in combination. This business rule requires confirmation.
- **Data Updates:** Conflicting records and changes to participant or course information require a defined update and versioning strategy.