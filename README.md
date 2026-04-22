# Brainspread

A web-based knowledge management system with hierarchical note-taking, daily journaling, and AI chat integration.

## Features

Brainspread is a Django web application that provides:

### Knowledge Management
- **Hierarchical notes**: Create and organize nested blocks of content
- **Daily notes**: Automatic daily note pages for journaling and task tracking
- **TODO management**: Built-in todo functionality with ability to move undone items between days
- **Pages and blocks**: Flexible content organization with pages containing nested blocks
- **Historical view**: Browse past daily notes and track progress over time

### AI Integration
- **Multi-provider support**: Integrates with OpenAI, Anthropic, and Google AI services
- **Chat interface**: Built-in AI chat with conversation history
- **Configurable models**: Support for different AI models per provider

### User Experience
- **Modern web interface**: Clean, responsive UI built with vanilla JavaScript
- **Real-time interactions**: Dynamic content updates without page refreshes  
- **User authentication**: Secure user accounts with customizable themes and timezones
- **Settings management**: Configurable AI provider settings and preferences

## Architecture

- **Backend**: Django with PostgreSQL database
- **Frontend**: Vanilla JavaScript with modular components
- **Deployment**: Docker Compose setup with separate web and database containers
- **Patterns**: Command pattern for business logic, repository pattern for data access

## Development Setup

See `.ai/PROJECT_SETUP.md` for detailed development instructions and setup guides.


<!-- Fix #51 -->
