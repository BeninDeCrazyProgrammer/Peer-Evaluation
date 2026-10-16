"""
Parses the lecturer's groups spreadsheet into a clean structure:

    [
      {"group_label": "1", "students": [{"name": "...", "student_id": "..."}, ...]},
      {"group_label": "2", "students": [...]},
      ...
    ]

Handles the normal case confirmed against a real sample sheet:
    Group Number | Name | ID
where Group Number is only filled on each group's first row (merged-cell
style in the original spreadsheet) and blank/NaN on the rest — those blanks
are forward-filled to their group.

Column names are matched loosely (case-insensitive, partial match) since the
lecturer's exact headers can vary, e.g. "ID" vs "Student ID" vs "Index Number".

Student IDs are only enforced unique per group in the database (see the
UNIQUE(group_id, student_id) constraint in models.py), not per course — so a
duplicate ID typo'd into two different groups won't get caught by the DB.
That's the identifier students log into an evaluation with, so a collision
means two students can't reliably log in until the lecturer fixes it. This
parser flags duplicate IDs (and duplicate names, which are recoverable but
still worth a heads-up) as warnings at upload time, before it becomes a
student-facing login problem.
"""
import pandas as pd
from collections import Counter


GROUP_COL_HINTS = ["group"]
NAME_COL_HINTS = ["name"]
ID_COL_HINTS = ["id", "index"]


def _find_column(columns, hints):
    for col in columns:
        col_lower = str(col).strip().lower()
        if any(hint in col_lower for hint in hints):
            return col
    return None


def parse_groups_excel(file_path_or_buffer):
    """
    Returns (groups, warnings).
    groups: list of {"group_label": str, "students": [{"name": str, "student_id": str}]}
    warnings: list of human-readable strings about rows that were skipped or ambiguous.
    """
    df = pd.read_excel(file_path_or_buffer)
    df.columns = [str(c).strip() for c in df.columns]

    group_col = _find_column(df.columns, GROUP_COL_HINTS)
    name_col = _find_column(df.columns, NAME_COL_HINTS)
    id_col = _find_column(df.columns, ID_COL_HINTS)

    warnings = []
    missing = [
        label for label, col in
        [("a group column", group_col), ("a name column", name_col), ("an ID column", id_col)]
        if col is None
    ]
    if missing:
        raise ValueError(
            f"Couldn't find {', '.join(missing)} in the sheet. "
            f"Columns found were: {list(df.columns)}"
        )

    # Forward-fill the group column to handle merged-cell-style blanks
    df[group_col] = df[group_col].ffill()

    groups = []
    for group_label, group_df in df.groupby(group_col, sort=False):
        students = []
        for _, row in group_df.iterrows():
            name = row.get(name_col)
            student_id = row.get(id_col)
            if pd.isna(name) or pd.isna(student_id):
                warnings.append(
                    f"Skipped a row in group '{group_label}' — missing name or ID."
                )
                continue
            students.append({
                "name": str(name).strip(),
                "student_id": str(student_id).strip(),
            })
        if len(students) < 2:
            warnings.append(
                f"Group '{group_label}' has fewer than 2 students — peer evaluation needs at least 2."
            )
        groups.append({"group_label": str(group_label).strip(), "students": students})

    # Flag IDs/names that repeat across the whole course, not just within one
    # group — a duplicate ID breaks student login (it's only unique per group
    # in the DB); a duplicate name is fine to leave, but that student will
    # need to use their ID rather than their name to log in.
    id_counts = Counter()
    name_counts = Counter()
    for g in groups:
        for s in g["students"]:
            id_counts[s["student_id"]] += 1
            name_counts[s["name"].lower()] += 1

    dup_ids = sorted(sid for sid, count in id_counts.items() if count > 1)
    if dup_ids:
        warnings.append(
            f"These student IDs appear more than once across different groups, which will stop those "
            f"students from logging in: {', '.join(dup_ids)}. Please fix the duplicate(s) and re-upload."
        )

    dup_names = sorted(name for name, count in name_counts.items() if count > 1)
    if dup_names:
        warnings.append(
            f"These names appear more than once across different groups: {', '.join(dup_names)}. "
            f"Those students should log in with their student ID rather than their name."
        )

    return groups, warnings
