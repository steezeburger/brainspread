// config.rs
use serde::{Deserialize, Serialize};

/// The global configuration for the application.
#[derive(Serialize, Deserialize)]
pub struct Config {
    /// openai api key
    pub openai_api_key: String,
}
