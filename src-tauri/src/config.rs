// config.rs
use serde::{Deserialize, Serialize};

/// The global configuration for the application.
#[derive(Serialize, Deserialize)]
pub struct Config {
    /// openapi api key
    pub openapi_api_key: String,
}
