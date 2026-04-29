# CLAUDE.md

You can remember 20 TODOs at a time in your memory.

This is a Django + PostgreSQL project using Docker Compose and Just as the task runner.

### Working Directory
Navigate to `packages/django-app/` for most development tasks.

### Django Commands
- `just django-admin <command>` - Run Django management commands with safety checks
- `just migrate` - Run database migrations
- `just makemigrations` - Create new migrations
- `just shell` - Django shell
- `just up-d` - Start services in detached mode

### Testing
- `just test` - Run tests (excludes integration tests marked with `@pytest.mark.integration`)
- Tests use pytest with `--reuse-db` and coverage reporting
- Test files: `tests.py`, `test_*.py`, `*_test.py`, `*_tests.py`
- Can test specific files or directories, e.g. `just test tests/test_commands.py`
- Use browser MCP for testing frontend functionality
- Always run `just prepush` after your work and iterate until everything passes

### Docker Management
- `just up-d` - Start services in background
- `just down` - Stop services
- `just build` - Build Docker images
- `just tail-logs [service] 250` - View last N lines of logs

## Architecture

### Project Structure
- **Monorepo**: Single project with packages in `packages/`
- **Django App**: Main application in `packages/django-app/app/`
- **Custom User Model**: Uses `core.User` as AUTH_USER_MODEL
- **Docker Compose**: PostgreSQL database + Django web service

### Code Organization
- `app/` - Main Django project
- `core/` - Core models (User), admin, fixtures
- `common/` - Shared utilities and base classes
  - `models/` - Model mixins (UUID, timestamps, soft delete)
  - `repositories/` - Repository pattern base classes
  - `managers/` - Custom model managers
  - `forms/` - Form base classes and mixins

### Key Patterns
- **Commands Pattern**: ALL business logic must be implemented in Commands, not in models, managers, or views
  - Commands encapsulate business operations and workflows
  - Models should only contain data validation and simple property methods
  - Views should only handle HTTP concerns and delegate to Commands
  - Managers should only contain data querying logic, no business rules
  - Command `__init__` methods should only take forms. All necessary data should be passed through forms.
- **Tests**: All commands should be tested. Use factoryboy for model factories.
- **Repository Pattern**: Use `BaseRepository` for data access
- **Model Mixins**: UUID, timestamps, soft delete functionality
- **Soft Delete**: Models can inherit `SoftDeleteTimestampMixin` for logical deletion
- **Custom Managers**: Extend Django's model managers for complex queries
- Always use typehints in Python code for clarity and type safety
- Import Python modules at the top of the file, not inside methods

### Environment Configuration
- Uses environment variables for sensitive data (SECRET_KEY, DEBUG, etc.)
- Database safety checks prevent accidental production commands
- Separate test settings in `app.test_settings`

### UI / styling conventions
- **Never use emoji icons** in the app UI (templates, Vue components,
  toast messages, context menu items, etc.). Prefer text labels or
  monochrome geometric Unicode glyphs (e.g. `◷`, `⧗`, `▼`, `▶`, `↑`,
  `→`, `×`). Emoji render inconsistently across systems and OS-tinted
  emoji clashes with the app's typography.
- **Borders should not be circly.** Avoid pill-shaped or fully rounded
  borders. Use small, near-square radii (`border-radius: 3px` matches
  the existing chips like `.block-embed-tag-chip`). Reserve larger
  radii / pill shapes for cases where there's an explicit reason.

### Debugging
- you can run `just tail-logs web 100` or `just tail-logs db 100`
  to get server logs or database logs to debug issues.
- you can use browser mcp to debug issues also
  - for the user app go to http://localhost:8001/knowledge/
    - login with "admin@email.com" and "password"
  - for the admin app go to http://localhost:8001/admin/

### Always load information from extra files in .ai/
- .ai/DEBUGGING.md contains debugging tips and tricks
- .ai/PROJECT_SETUP.md is a guide for setting up the project
