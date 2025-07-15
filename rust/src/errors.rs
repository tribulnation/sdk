#[derive(Debug, Clone)]
pub struct BaseError {
  pub detail: String,
}

#[derive(Debug, Clone)]
pub struct NetworkFailure(BaseError);

#[derive(Debug, Clone)]
pub struct InvalidParams(BaseError);

#[derive(Debug, Clone)]
pub struct InvalidResponse(BaseError);

#[derive(Debug, Clone)]
pub struct InvalidAuth(BaseError);

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