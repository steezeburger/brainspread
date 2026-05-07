# Project Setup Steps

This document outlines the completed setup steps for the Brainspread Django MVP project.

> **Looking for a non-Docker workflow?** See [LOCAL_SETUP.md](./LOCAL_SETUP.md)
> for two alternatives: (B) Docker for Postgres + uv for Django, and
> (C) fully local with no Docker at all. Use those when you need IDE
> debugging against a real interpreter or when you're in an environment
> that can't run a Docker daemon (e.g. Claude Code on web).

## Prerequisites
- Docker and Docker Compose installed
- Just task runner installed

## Setup Steps Completed

### 1. Navigate to Project Directory
```bash
cd packages/django-app
```

### 2. Create Environment File
```bash
just copy-env
```
This copies `.env.template` to `.env` with default configuration.

### 3. Generate Django Secret Key
```bash
just generate-secret-key
```
Copy the output and manually update the `DJANGO_SECRET_KEY` in your `.env` file.

### 4. Create Docker Volumes and Build Images
```bash
just create-volumes
just build
```

### 5. Start Database Service
```bash
just up-d db
```

### 6. Run Database Migrations
```bash
just migrate
```

### 7. Load Development Data
```bash
just reload-db
```
This command:
- Recreates the database volume and container
- Runs migrations
- Loads `dev_data.json` fixture with admin user

### 8. Start Development Server
```bash
just up
```

## Project Status
✅ **Setup Complete** - Ready for MVP development

## Access Information
- **Web Application**: http://localhost:8001/
- **Admin Panel**: http://localhost:8001/admin/
- **Admin Credentials**: admin@email.com / password

## Key Just Commands for Development
- `just up` - Start all services
- `just down` - Stop all services  
- `just migrate` - Run database migrations
- `just makemigrations` - Create new migrations
- `just test` - Run tests
- `just shell` - Django shell
- `just reload-db` - Reset database with test data
- `just logs` - View container logs
- `just ps` - Show container status
- `just copy-env` - Copy environment template
- `just generate-secret-key` - Generate Django secret key

## Environment Configuration
- Django Secret Key: ✅ Configured
- Database: ✅ PostgreSQL running in Docker
- Debug Mode: ✅ Enabled for development
- Admin User: ✅ Available via fixture data