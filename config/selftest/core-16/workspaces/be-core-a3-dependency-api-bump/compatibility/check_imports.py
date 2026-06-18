from aggregator import total_fields
from loader import load_records

assert load_records("x,y") == [["x", "y"]]
assert total_fields("a,b\nc") == 3
