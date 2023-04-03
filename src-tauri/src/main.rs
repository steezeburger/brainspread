#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

use tauri::State;
use tokio::runtime::Builder;
use tokio::sync::Mutex;

use app::get_config;
use app::services::db::DB;
use app::types::Database;

/// The entrypoint to our Tauri application.
/// This is where we will initialize and migrate our database connection,
/// setup State, and register our command handlers.
fn main() {
    let config = get_config().expect("Failed to get config");

    // Create a Tokio runtime with the current_thread scheduler
    let runtime = Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("Failed to create Tokio runtime");

    // Use an async block to run async code inside the runtime
    let db_result = runtime.block_on(async { DB::new(&config.database_url).await });

    if let Ok(db) = db_result {
        let database = Database {
            db: Mutex::new(Some(db)),
            database_url: config.database_url.to_string(),
        };

        tauri::Builder::default()
            .manage(database)
            .manage(config.clone())
            .invoke_handler(tauri::generate_handler![greet, submit_text])
            .run(tauri::generate_context!())
            .expect("Error while running Tauri application");
    } else {
        panic!("Database failure: {:?}", db_result.err().unwrap());
    }
}

#[tauri::command]
async fn greet(name: &str) -> Result<String, String> {
    Ok(format!("Hello, {}!", name))
}

#[tauri::command]
async fn submit_text(text: &str, database: State<'_, Database>) -> Result<(), String> {
    let mut db_guard = database.db.lock().await;
    let db = db_guard.as_mut().ok_or("Database not available")?;

    let query = format!(
        "INSERT INTO contents (title, content) VALUES ('{}', '{}')",
        "test contents", text
    );

    // TODO - error handling
    let rows_affected = db.execute(&query).await.expect("Failed to execute query");

    println!("Inserted new text, {} rows affected", rows_affected);

    Ok(())
}
