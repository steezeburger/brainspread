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
# copy the example config to the correct location.
# you'll need to set the openai api key and also a location for the database.
# i recommend putting the db in the `src-tauri/db/` directory.
cp src-tauri/BrainSpreadConfig.toml.example src-tauri/BrainSpreadConfig.toml

# run the tauri app
cargo tauri dev
```

### migrations
```bash
# install the sqlx-cli
cargo install sqlx-cli --features native-tls,sqlite

# it's best to be in the db directory when running sqlx commands, 
# but you can also specify the path to the db file via `--database-url`, 
# except for the `migrate add` command. 
# that seems to just create the migration in `./migrations/` regardless of where you are.
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
