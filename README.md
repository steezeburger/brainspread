# BrainSpread

This app is powered by Rust and Javascript with Tauri and Next.js.

### development

pre-requisites:

First, get `BrainSpreadConfig.toml` from steezeburger and place it in `src-tauri`, or copy `BrainSpreadConfig.toml.example` and fill in the values.

```bash
# install npm deps
npm install

# install tauri-cli
cargo install tauri-cli

 ```

running for development:

```bash
cargo tauri dev
```

### migrrations
```bash
# install the sqlx-cli
cargo install sqlx-cli --features native-tls,sqlite

# best to be in the db directory when running these commands
cd src-tauri/db

# create the database
sqlx database create --database-url=sqlite://brainspread_dev.db

# create a new migration. will add file in ./migrations/
sqlx migrate add -r <migration_name>

# run the migrations
sqlx migrate run --database-url=sqlite://brainspread_dev.db

# revert the last migration
sqlx migrate revert --database-url=sqlite://brainspread_dev.db
```
