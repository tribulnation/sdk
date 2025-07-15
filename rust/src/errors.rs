#[derive(Debug, Clone)]
pub struct NetworkFailure {
  pub detail: String,
}

#[derive(Debug, Clone)]
pub struct InvalidParams {
  pub detail: String,
}

#[derive(Debug, Clone)]
pub struct InvalidResponse {
  pub detail: String,
}

#[derive(Debug, Clone)]
pub struct InvalidAuth {
  pub detail: String,
}

#[derive(Debug, Clone)]
pub enum UnauthedError {
  NetworkFailure(NetworkFailure),
  InvalidParams(InvalidParams),
  InvalidResponse(InvalidResponse),
}

#[derive(Debug, Clone)]
pub enum AuthedError {
  NetworkFailure(NetworkFailure),
  InvalidParams(InvalidParams),
  InvalidResponse(InvalidResponse),
  InvalidAuth(InvalidAuth),
}