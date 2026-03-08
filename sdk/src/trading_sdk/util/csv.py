from typing_extensions import Mapping, Any, Collection, Literal
from dataclasses import dataclass
from datetime import datetime
import re
import pandas as pd

Schema = Mapping[str|re.Pattern, type|re.Pattern]

def ensure_datetime(x, *, format: Literal['iso'] = 'iso') -> datetime:
  if isinstance(x, datetime):
    return x
  else:
    return datetime.fromisoformat(str(x))

@dataclass
class MissingColumn:
  column: str | re.Pattern
  expected_type: type | re.Pattern

  def __str__(self):
    return f'Column "{self.column}" is missing (expected type: {self.expected_type})'

@dataclass
class InvalidColumnType:
  column: str
  expected_type: type
  actual_type: type
  example_value: Any

  def __str__(self):
    return f'Column "{self.column}" has type {self.actual_type} (expected {self.expected_type})'

@dataclass
class InvalidColumnString:
  column: str
  expected_type: re.Pattern
  wrong_values: Collection[str]

  def __str__(self):
    return f'Column "{self.column}" has invalid values (expected it to match {self.expected_type.pattern}). Wrong values: {", ".join(list(self.wrong_values)[:10])}'

SchemaError = MissingColumn | InvalidColumnType | InvalidColumnString

class InvalidSchema(Exception):
  def __init__(self, errors: list[SchemaError], *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.errors = errors

  def __str__(self):
    out = 'Schema Validation Error:\n'
    for error in self.errors:
      out += f'> {error}\n'
    return out

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
  errors: list[SchemaError] = []
  for expected_key, expected_type in schema.items():
    key = find_key(df, expected_key)
    if key is None:
      errors.append(MissingColumn(expected_key, expected_type))
      continue
    
    if isinstance(expected_type, re.Pattern):
      ok = df[key].astype(str).str.match(expected_type).all()
      if not ok:
        wrong_values = set[str](df[key][~df[key].astype(str).str.match(expected_type)].unique()) # type: ignore
        errors.append(InvalidColumnString(key, expected_type, wrong_values))
    
    elif expected_type is not Any and len(df) > 0:
      row = df.iloc[0]
      if not isinstance(row[key], expected_type):
        errors.append(InvalidColumnType(key, expected_type, type(row[key]), row[key]))

  if len(errors) > 0:
    raise InvalidSchema(errors)