class Error(Exception):
  def __str__(self):
    args = self.args[0] if len(self.args) == 1 else ', '.join(self.args)
    return f'{self.__class__.__name__}({args})'

class NetworkError(Error):
  def __str__(self):
    return super().__str__()

class ValidationError(Error):
  def __str__(self):
    return super().__str__()

class UserError(Error):
  def __str__(self):
    return super().__str__()

class AuthError(Error):
  def __str__(self):
    return super().__str__()

class ApiError(Error):
  def __str__(self):
    return super().__str__()
