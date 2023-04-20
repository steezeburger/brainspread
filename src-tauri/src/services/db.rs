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

    /// Get the most recent content from the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let most_recent_content = db.get_most_recent_content().await?;
    /// ```
    pub async fn get_most_recent_content(&self) -> Result<Option<(i32, String)>, sqlx::Error> {
        let query = "SELECT id, title FROM contents WHERE id = (SELECT MAX(id) FROM contents)";
        let mut conn = self.pool.acquire().await?;
        let row: Option<(i32, String)> = sqlx::query_as::<_, (i32, String)>(query)
            .fetch_optional(&mut conn)
            .await?;
        Ok(row)
    }

    /// Insert new content into the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows_affected = db.insert_content("New Content", "This is new content").await?;
    /// ```
    pub async fn insert_content(&self, title: &str, content: &str) -> Result<u64, sqlx::Error> {
        let query = "INSERT INTO contents (title, content) VALUES (?, ?)";
        let mut conn = self.pool.acquire().await?;
        let rows_affected = sqlx::query(query)
            .bind(title)
            .bind(content)
            .execute(&mut conn)
            .await?
            .rows_affected();
        Ok(rows_affected)
    }

    /// Insert new summary into the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows_affected = db.insert_summary(1, "This is a summary").await?;
    /// ```
    pub async fn insert_summary(&self, content_id: i32, summary: &str) -> Result<u64, sqlx::Error> {
        let query = "INSERT INTO summaries (content_id, content) VALUES (?, ?)";
        let mut conn = self.pool.acquire().await?;
        let rows_affected = sqlx::query(query)
            .bind(content_id)
            .bind(summary)
            .execute(&mut conn)
            .await?
            .rows_affected();
        Ok(rows_affected)
    }

    /// Insert new labels into the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows_affected = db.insert_labels(1, vec!["label1".to_string(), "label2".to_string()]).await?;
    /// ```
    pub async fn insert_labels(
        &self,
        content_id: i32,
        labels: Vec<String>,
    ) -> Result<u64, sqlx::Error> {
        let query = "INSERT INTO labels (content_id, name) VALUES (?, ?)";
        let mut conn = self.pool.acquire().await?;
        let mut rows_affected = 0;
        for label in labels {
            rows_affected += sqlx::query(query)
                .bind(content_id)
                .bind(label)
                .execute(&mut conn)
                .await?
                .rows_affected();
        }
        Ok(rows_affected)
    }
}
