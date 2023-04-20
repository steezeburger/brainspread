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
            .invoke_handler(tauri::generate_handler![greet, get_summary_and_labels])
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

#[derive(serde::Serialize)]
struct SummaryAndLabelsResponse {
    summary: String,
    labels: Vec<String>,
}

#[tauri::command]
async fn get_summary_and_labels(
    title: &str,
    text: &str,
    database: State<'_, Database>,
) -> Result<SummaryAndLabelsResponse, String> {
    let mut db_guard = database.db.lock().await;
    let db = db_guard.as_mut().ok_or("Database not available")?;

    // TODO - error handling
    let rows_affected = db
        .insert_content(title, text)
        .await
        .expect("Failed to insert content");
    println!("Inserted new text, {} rows affected", rows_affected);

    // get most recent content id
    let content = db
        .get_most_recent_content()
        .await
        .expect("Failed to get most recent content");
    let content_id = content.expect("No content found").0;

    // generate summary
    let summary = app::services::openai::generate_summary(title, text)
        .await
        .expect("Failed to generate summary");

    // create summary in db
    let rows_affected = db
        .insert_summary(content_id, summary.as_str())
        .await
        .expect("Failed to insert summary");
    println!("Inserted new summary, {} rows affected", rows_affected);

    // generate labels
    let labels = app::services::openai::generate_labels(title, text)
        .await
        .expect("Failed to generate labels");
    // insert labels into database
    let rows_affected = db
        .insert_labels(content_id, labels.clone())
        .await
        .expect("Failed to insert labels");
    println!("Inserted new labels, {} rows affected", rows_affected);

    Ok(SummaryAndLabelsResponse { summary, labels })
}
