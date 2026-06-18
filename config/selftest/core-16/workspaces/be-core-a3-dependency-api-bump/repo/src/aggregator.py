from loader import load_records


def total_fields(blob: str) -> int:
    return sum(len(row) for row in load_records(blob))
