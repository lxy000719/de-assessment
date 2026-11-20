import logging
import sqlite3
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "courses.db"
CSV_PATH = PROJECT_ROOT / "data" / "enrolments.csv"
REJECT_PATH = PROJECT_ROOT / "data" / "rejected_enrolments.csv"

REQUIRED_COLUMNS = [
    "enrollment_id",
    "participant_id",
    "participant_name",
    "course_id",
    "course_date",
    "amount",
    "subsidy",
    "credits_used",
]

FINANCIAL_COLUMNS = ["amount", "subsidy", "credits_used"]
ID_COLUMNS = ["enrollment_id", "course_id"]

DATE_FORMATS = [
    "%d/%m/%Y",
    "%Y-%m-%d",
    "%d %b %Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

def parse_course_date(value):
    """Parse supported date formats into ISO format."""
    if pd.isna(value):
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(
                str(value).strip(), fmt
            ).date().isoformat()
        except ValueError:
            continue

    return None

def read_csv():
    """Read the source CSV and check required columns."""
    df = pd.read_csv(CSV_PATH, dtype=str)

    missing_cols = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing columns: {sorted(missing_cols)}")

    return df[REQUIRED_COLUMNS].copy()


def validate_and_transform(df, valid_course_ids):
    """Separate valid and rejected enrollment records."""
    clean_df = df.copy()

    # Store multiple validation errors per row
    errors = pd.Series(
        [[] for _ in range(len(df))],
        index=df.index,
    )

    def add_error(mask, message):
        for idx in df.index[mask]:
            errors.at[idx].append(message)

    # 1. Missing values
    add_error(
        clean_df[REQUIRED_COLUMNS].isna().any(axis=1),
        "Missing required value",
    )

    # 2. Validate IDs
    for col in ["enrollment_id", "course_id"]:
        numeric = pd.to_numeric(clean_df[col], errors="coerce")

        invalid = (
            ~np.isfinite(numeric.to_numpy(dtype=float))
            | (numeric <= 0)
            | (numeric % 1 != 0)
        )

        add_error(
            pd.Series(invalid, index=df.index),
            f"Invalid {col}",
        )

        clean_df[col] = numeric

    # 3. Duplicate enrollment IDs
    add_error(
        clean_df["enrollment_id"].duplicated(keep=False),
        "Duplicate enrollment ID",
    )

    # 4. Course ID must exist in courses table
    add_error(
        ~clean_df["course_id"].isin(valid_course_ids),
        "Unknown course ID",
    )

    # 5. Date validation and standardization
    clean_df["course_date"] = (
        clean_df["course_date"].apply(parse_course_date)
    )

    add_error(
        clean_df["course_date"].isna(),
        "Invalid course date",
    )

    # 6. Financial validation
    for col in FINANCIAL_COLUMNS:
        clean_df[col] = pd.to_numeric(
            clean_df[col], errors="coerce"
        )

    invalid_numeric = ~np.isfinite(
        clean_df[FINANCIAL_COLUMNS].to_numpy(dtype=float)
    ).all(axis=1)

    add_error(
        pd.Series(invalid_numeric, index=df.index),
        "Invalid financial value",
    )

    add_error(
        (clean_df[FINANCIAL_COLUMNS] < 0).any(axis=1),
        "Negative financial value",
    )

    # subsidy + credits_used cannot exceed amount
    add_error(
        clean_df["subsidy"] + clean_df["credits_used"]
        > clean_df["amount"] + 1e-9,
        "Subsidy + credits exceed amount",
    )

    # 7. Separate valid and rejected records
    rejected_mask = errors.apply(bool)

    valid_df = clean_df.loc[~rejected_mask].copy()
    rejected_df = df.loc[rejected_mask].copy()

    rejected_df["validation_error"] = (
        errors.loc[rejected_mask].apply("; ".join)
    )

    valid_df["enrollment_id"] = (
        valid_df["enrollment_id"].astype(int)
    )
    valid_df["course_id"] = (
        valid_df["course_id"].astype(int)
    )

    return valid_df, rejected_df


def load_to_sqlite(conn, valid_df):
    """Insert new enrollments without duplicating existing IDs."""
    sql = """
        INSERT INTO enrollments (
            enrollment_id,
            participant_id,
            participant_name,
            course_id,
            course_date,
            amount,
            subsidy,
            credits_used
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(enrollment_id) DO NOTHING
    """

    records = list(
        valid_df[REQUIRED_COLUMNS].itertuples(
            index=False, name=None
        )
    )

    before = conn.total_changes

    # Transaction: commit all inserts or rollback on error
    with conn:
        conn.executemany(sql, records)

    inserted = conn.total_changes - before
    skipped = len(records) - inserted

    return inserted, skipped


def run_pipeline():
    """Validate, load, and report ingestion results."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(DB_PATH)

    df = read_csv()

    with sqlite3.connect(DB_PATH) as conn:
        valid_course_ids = {
            row[0]
            for row in conn.execute(
                "SELECT course_id FROM courses"
            )
        }

        valid_df, rejected_df = validate_and_transform(
            df, valid_course_ids
        )

        inserted, skipped = load_to_sqlite(
            conn, valid_df
        )

    rejected_df.to_csv(REJECT_PATH, index=False)

    logger.info("Source records: %d", len(df))
    logger.info("Valid records: %d", len(valid_df))
    logger.info("Rejected records: %d", len(rejected_df))
    logger.info("Inserted records: %d", inserted)
    logger.info("Skipped existing records: %d", skipped)


if __name__ == "__main__":
    run_pipeline()