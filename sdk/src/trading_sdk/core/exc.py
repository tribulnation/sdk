class Error(Exception):
  """Base SDK exception."""
  def __str__(self):
    args = self.args[0] if len(self.args) == 1 else ', '.join(self.args)
    return f'{self.__class__.__name__}({args})'

class NetworkError(Error):
  """Network error: HTTP error, connection timeout, etc."""
  def __str__(self):
    return super().__str__()

class ValidationError(Error):
  """Validation error: invalid response, invalid data, etc."""
  def __str__(self):
    return super().__str__()

class UserError(Error):
  """User error: invalid request, invalid input, etc."""
  def __str__(self):
    return super().__str__()

class AuthError(Error):
  """Authentication error: invalid API key, invalid API secret, etc."""
  def __str__(self):
    return super().__str__()

class ApiError(Error):
  """Unknown error returned by the API."""
  def __str__(self):
    return super().__str__()

class LogicError(Error):
  """Logic error: invalid assumptions, logic, or other bugs on the SDK side."""
  def __str__(self):
    return super().__str__()
