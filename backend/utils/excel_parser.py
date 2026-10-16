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
"""
import pandas as pd


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

    return groups, warnings
