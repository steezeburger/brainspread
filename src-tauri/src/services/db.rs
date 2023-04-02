use std::str::FromStr;

use sqlx::sqlite::SqliteConnectOptions;
use sqlx::SqlitePool;

/// DB is a wrapper around Sqlite that provides a connection pool and methods to execute queries.
pub struct DB {
    /// The sqlite connection pool.
    pool: SqlitePool,
}

impl DB {
    /// Create a new instance and establish a connection with the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let db = DB::new().await?;
    /// ```
    pub async fn new(database_url: &str) -> Result<Self, sqlx::Error> {
        let options = SqliteConnectOptions::from_str(database_url)?
            .foreign_keys(true)
            .journal_mode(sqlx::sqlite::SqliteJournalMode::Wal);

        let pool = SqlitePool::connect_with(options).await?;

        Ok(Self { pool })
    }

    /// Execute a query to read data from the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows: Vec<(i32, String)> = db.query("SELECT id, name FROM some_table").await?;
    /// ```
    pub async fn query<T: for<'q> sqlx::FromRow<'q, sqlx::sqlite::SqliteRow> + Send + Unpin>(
        &self,
        query: &str,
    ) -> Result<Vec<T>, sqlx::Error> {
        let mut conn = self.pool.acquire().await?;
        let rows = sqlx::query_as::<_, T>(query).fetch_all(&mut conn).await?;
        Ok(rows)
    }


    /// Execute a query to write data to the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows_affected = db.execute("INSERT INTO some_table (name) VALUES ('New Entry')").await?;
    /// ```
    pub async fn execute(&self, query: &str) -> Result<u64, sqlx::Error> {
        let mut conn = self.pool.acquire().await?;
        let rows_affected = sqlx::query(query).execute(&mut conn).await?.rows_affected();
        Ok(rows_affected)
    }
}
