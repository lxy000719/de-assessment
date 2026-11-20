from src.ingest import parse_course_date, validate_and_transform, load_to_sqlite
import pandas as pd
import sqlite3

def test_valid_date():
    """Accept supported date formats."""
    assert parse_course_date("15/01/2024") == "2024-01-15"
    assert parse_course_date("2024-01-15") == "2024-01-15"
    assert parse_course_date("15 Jan 2024") == "2024-01-15"

def test_invalid_date():
    """Reject invalid dates."""
    assert parse_course_date("2023-02-29") is None
    assert parse_course_date("invalid") is None

def make_enrollment(**overrides):
    """Build a valid enrollment with optional field overrides."""
    record = {
        "enrollment_id": "101",
        "participant_id": "P001",
        "participant_name": "Alice",
        "course_id": "1",
        "course_date": "2024-01-15",
        "amount": "500",
        "subsidy": "100",
        "credits_used": "50",
    }
    record.update(overrides)
    return record

def test_valid_enrollment():
    """Accept a valid enrollment."""
    df = pd.DataFrame([make_enrollment()])

    valid, rejected = validate_and_transform(df, {1})

    assert len(valid) == 1
    assert len(rejected) == 0

def test_negative_amount():
    """Reject negative financial amounts."""
    df = pd.DataFrame([make_enrollment(amount="-100")])

    valid, rejected = validate_and_transform(df, {1})

    assert len(valid) == 0
    assert "Negative financial value" in rejected.iloc[0]["validation_error"]

def test_unknown_course():
    """Reject references to unknown courses."""
    df = pd.DataFrame([make_enrollment(course_id="999")])

    valid, rejected = validate_and_transform(df, {1})

    assert len(valid) == 0
    assert "Unknown course ID" in rejected.iloc[0]["validation_error"]

def test_duplicate_enrollment():
    """Reject duplicate enrollment IDs in the source batch."""
    df = pd.DataFrame([
        make_enrollment(),
        make_enrollment(participant_id="P002"),
    ])

    valid, rejected = validate_and_transform(df, {1})

    assert len(valid) == 0
    assert len(rejected) == 2

def test_idempotent_insert():
    """Verify repeated loads do not duplicate records."""
    conn = sqlite3.connect(":memory:")

    try:
        conn.execute("""
            CREATE TABLE enrollments (
                enrollment_id INTEGER PRIMARY KEY,
                participant_id TEXT,
                participant_name TEXT,
                course_id INTEGER,
                course_date DATE,
                amount REAL,
                subsidy REAL,
                credits_used REAL
            )
        """)

        df = pd.DataFrame([make_enrollment()])
        valid, rejected = validate_and_transform(df, {1})

        assert rejected.empty

        first_inserted, first_skipped = load_to_sqlite(conn, valid)
        second_inserted, second_skipped = load_to_sqlite(conn, valid)

        assert first_inserted == 1
        assert first_skipped == 0
        assert second_inserted == 0
        assert second_skipped == 1

        count = conn.execute(
            "SELECT COUNT(*) FROM enrollments"
        ).fetchone()[0]

        assert count == 1

    finally:
        conn.close()