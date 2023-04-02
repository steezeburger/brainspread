use crate::services::db::DB;
use tokio::sync::Mutex;

/// Database is a wrapper around DB that provides a Mutex to allow for concurrent access.
pub struct Database {
    /// The database connection.
    pub db: Mutex<Option<DB>>,

    /// The database url.
    pub database_url: String,
}
