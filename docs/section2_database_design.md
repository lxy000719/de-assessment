# Section 2 — Database Design

## Bronze Layer - Preserve Raw Data and Add Metadata

TODO

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