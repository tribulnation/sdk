from typing_extensions import Mapping, Any, Iterable
import re
import pandas as pd

Schema = Mapping[str|re.Pattern, type|re.Pattern]

def find_key(df: pd.DataFrame, key: str | re.Pattern) -> str | None:
  keys = list(df.dtypes.keys())
  if isinstance(key, str):
    if key in keys:
      return key
  else:
    for k in keys:
      if key.match(k):
        return k

def validate_schema(df: pd.DataFrame, schema: Schema):
  for expected_key, expected_type in schema.items():
    key = find_key(df, expected_key)
    if key is None:
      raise ValueError(f'Column "{expected_key}" not found')
    
    if isinstance(expected_type, re.Pattern):
      ok = df[key].astype(str).str.match(expected_type).all()
      if not ok:
        raise ValueError(f'Column "{expected_key}" has invalid values (expected it to match {expected_type.pattern})')
    elif expected_type is not Any and len(df) > 0:
      row = df.iloc[0]
      if not isinstance(row[key], expected_type):
        raise ValueError(f'Column "{expected_key}" has type {type(row[key])} (expected {expected_type})')