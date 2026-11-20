# Section 1 — Data Ingestion

## Overview

The ingestion script loads enrollment records from `data/enrolments.csv` into the existing SQLite database at `data/courses.db`. It validates and standardizes source records before inserting them into the `enrollments` table. The existing database schema is not modified.

**Implementation:** `src/ingest.py`  
**Tests:** `tests/test_ingest.py`  
**Rejected records:** `data/rejected_enrolments.csv`

## How to Run

From the project root:

```bash
uv sync
uv run python src/ingest.py
uv run python -m pytest -v
```

The source CSV and the existing SQLite database must be present in the `data/` directory. The script logs record counts to the console and writes rejected records to a separate CSV.

## Ingestion Workflow

1. **Read:** Load the source CSV as strings and verify that all required columns are present.
2. **Validate and transform:** Check identifiers, course references, dates, and financial values; standardize valid dates to `YYYY-MM-DD`.
3. **Separate:** Keep valid records for loading and export rejected records with their validation reasons.
4. **Load:** Insert valid rows into the existing `enrollments` table in a SQLite transaction.
5. **Report:** Log source, valid, rejected, inserted, and skipped record counts.

## Data Validation

| Check | Rule |
|---|---|
| Required fields | All required enrollment fields must be present and non-null. |
| Identifiers | `enrollment_id` and `course_id` must be positive integers. |
| Duplicate enrollment IDs | Reject all records sharing an `enrollment_id` within the source CSV. |
| Course reference | `course_id` must exist in the database's `courses` table. |
| Course date | Accept supported date formats and convert to ISO `YYYY-MM-DD`; reject invalid dates. |
| Financial fields | `amount`, `subsidy`, and `credits_used` must be finite, numeric, and non-negative. |
| Financial consistency | Assume `subsidy + credits_used <= amount`; reject records violating this rule. |

Multiple validation failures for the same row are collected in the `validation_error` column of the rejected-records CSV.

## Error Handling and Idempotency

Invalid source rows are excluded from insertion and written to `data/rejected_enrolments.csv` for review. A missing required CSV column or missing database file stops the pipeline rather than silently proceeding.

The loader uses the existing `enrollment_id` primary key and SQLite's `ON CONFLICT(enrollment_id) DO NOTHING`. Re-running the same file therefore does not create duplicate enrollments. Inserts are executed in a transaction, so a database insertion failure rolls back that insertion batch.

**Trade-off:** An existing enrollment ID is skipped rather than updated. Supporting corrected source records would require an explicit update or upsert policy.

## Testing

Seven automated pytest cases cover:

- Supported and invalid course-date inputs.
- Acceptance of a valid enrollment.
- Rejection of negative financial amounts and unknown course IDs.
- Rejection of duplicate enrollment IDs within the input.
- Idempotent loading, verified with an in-memory SQLite database.

Run the tests with:

```bash
uv run python -m pytest -v
```

**Observed result:** 7 tests passed.

## Execution Results

The following results were observed when running the provided source file:

| Metric | First run | Second run |
|---|---:|---:|
| Source records | 34 | 34 |
| Valid records | 33 | 33 |
| Rejected records | 1 | 1 |
| Inserted records | 33 | 0 |
| Skipped existing records | 0 | 33 |

The rejected record contained an invalid date (`2023-02-29`). The second run inserted no new records, demonstrating idempotency for an unchanged input file.

## Assumptions and Limitations

- The supplied SQLite database and `courses` reference data are authoritative; no schema changes are made.
- The financial consistency rule is a business assumption, not an explicitly confirmed policy.
- Duplicate enrollment IDs within one CSV are rejected; existing IDs in the database are skipped.
- Rejected rows are exported for review, but there is no automated correction or reprocessing workflow.
- Execution counts are logged to the console; persistent audit logging and production scheduling are outside the scope of this implementation.
