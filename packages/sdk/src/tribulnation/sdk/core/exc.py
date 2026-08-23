class Error(Exception):
  """Base SDK exception."""
  def __str__(self):
    args = self.args[0] if len(self.args) == 1 else ', '.join(map(str, self.args))
    return f'{self.__class__.__name__}({args})'

class NetworkError(Error):
  """Error reaching the server."""
  def __str__(self):
    return super().__str__()

class ValidationError(Error):
  """Invalid response format."""
  def __str__(self):
    return super().__str__()

class ApiError(Error):
  """Error returned by the API."""
  def __str__(self):
    return super().__str__()

class BadRequest(ApiError):
  """Bad request: invalid request, invalid input, etc."""
  def __str__(self):
    return super().__str__()

class AuthError(ApiError):
  """Authentication error: invalid API key, invalid API secret, etc."""
  def __str__(self):
    return super().__str__()

class RateLimited(ApiError):
  """Rate limited: the API has reached the rate limit."""
  def __str__(self):
    return super().__str__()

class LogicError(Error):
  """Logic error: invalid assumptions, logic, or other bugs on the SDK side."""
  def __str__(self):
    return super().__str__()
