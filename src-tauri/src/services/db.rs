use std::env;
use std::str::FromStr;

use sqlx::sqlite::SqliteConnectOptions;
use sqlx::SqlitePool;

/// DB is a wrapper around Sqlite that provides a connection pool and methods to execute queries.
pub struct DB {
    pool: SqlitePool,
}

impl DB {
    /// Create a new instance and establish a connection with the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let db = DB::new().await.unwrap();
    /// ```
    pub async fn new() -> Result<Self, sqlx::Error> {
        let database_url = env::var("DATABASE_URL").unwrap_or_else(|_| "../brainspread.sqlite".to_string());

        let options = SqliteConnectOptions::from_str(&database_url)?
            .create_if_missing(true)
            .foreign_keys(true)
            .journal_mode(sqlx::sqlite::SqliteJournalMode::Wal);

        let pool = SqlitePool::connect_with(options).await?;

        Ok(Self { pool })
    }

    /// Initializes the `brainspread` table if it does not exist.
    ///
    /// # Example
    ///
    /// ```
    /// db.init_table().await.unwrap();
    /// ```
    pub async fn init_table(&self) -> Result<(), sqlx::Error> {
        let create_table_query = r#"
        CREATE TABLE IF NOT EXISTS brainspread (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        "#;

        self.execute(create_table_query).await.map(|_| ())
    }

    /// Execute a query to read data from the SQLite database.
    ///
    /// # Example
    ///
    /// ```
    /// let rows: Vec<(i32, String)> = db.query("SELECT id, name FROM some_table").await.unwrap();
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
    /// let rows_affected = db.execute("INSERT INTO some_table (name) VALUES ('New Entry')").await.unwrap();
    /// ```
    pub async fn execute(&self, query: &str) -> Result<u64, sqlx::Error> {
        let mut conn = self.pool.acquire().await?;
        let rows_affected = sqlx::query(query).execute(&mut conn).await?.rows_affected();
        Ok(rows_affected)
    }
}
