# Section 3 – SQL Reporting

## 1. Objective

Identify participants who enrolled in courses without evidence of having met the required prerequisites before the course date.

The report returns **one row per potentially unmet prerequisite** for each course enrollment.

## 2. SQL Approach

The query in `sql/prerequisite_report.sql` uses the existing SQLite tables, `enrollments` and `courses`:

1. Join `enrollments` to `courses` to retrieve the enrolled course and its prerequisite list.
2. Use SQLite's `json_each()` to expand the `prerequisites` JSON array into individual prerequisite course IDs.
3. Join `courses` again to retrieve each prerequisite's name.
4. Use a `LEFT JOIN` to look for an earlier enrollment by the same participant in the prerequisite course.
5. Filter with `WHERE pe.enrollment_id IS NULL` to report prerequisites for which no qualifying earlier enrollment was found.

Courses without prerequisites do not produce report rows.

## 3. Assumptions and Limitations

- **Completion is not recorded.** The available data contains enrollments, not course completion statuses or completion dates. An earlier prerequisite enrollment is therefore used as a **proxy**, not proof, of completion.
- **Date comparison:** A prerequisite enrollment must have a `course_date` strictly earlier than the target enrollment's `course_date`. A same-day enrollment does not satisfy this rule.
- **Direct prerequisites only:** The query checks prerequisites explicitly listed for each course; it does not recursively check prerequisites of prerequisites.
- **Repeat enrollments:** The report evaluates each target enrollment separately. Any qualifying earlier enrollment in a prerequisite course is sufficient for this proxy check.
- **Date quality:** An unusual but syntactically valid date, such as `1900-06-10`, is retained because no authoritative business-valid date range was provided.

Accordingly, the results should be interpreted as **potentially unmet prerequisites**, not confirmed cases of incomplete prerequisite training.

## 4. Execution

From the project root:

```bash
uv run python -c "import sqlite3; c=sqlite3.connect('data/courses.db'); rows=c.execute(open('sql/prerequisite_report.sql').read()); print(*rows.description, sep='\n'); print(*rows.fetchall(), sep='\n')"
```

## 5. Observed Results

The previously executed prerequisite report returned **6 flagged prerequisite rows across 5 participants**:

| Participant | Enrolled Course | Prerequisite Without Earlier Enrollment |
|---|---|---|
| Alice Tan | CS201 Networking | CS200 Databases |
| Bob Lee | CS200 Databases | CS101 Data structures |
| Edward Goh | CS201 Networking | CS200 Databases |
| Henry Teo | CS200 Databases | CS100 Introduction to Computer Science |
| Henry Teo | CS200 Databases | CS101 Data structures |
| Irene Chua | CS300 Systems | CS201 Networking |

Henry Teo appears twice because two distinct prerequisites were flagged for the same course enrollment.

