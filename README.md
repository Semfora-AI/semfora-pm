# Semfora PM - EARLY BETA

Connect your AI coding assistant to Linear. Get full ticket context, track progress, and never miss a requirement again.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## Quick Start

```bash
# Install
pip install semfora-pm

# Set your Linear API key
export LINEAR_API_KEY=lin_api_...

# Initialize in your project
cd your-project
semfora-pm init

# Check sprint status
semfora-pm sprint status
```

## Features

- **Linear integration** - Bidirectional sync with Linear
- **Sprint tracking** - See what's in progress, todo, and done
- **Full context** - Get complete ticket details including acceptance criteria
- **AI-ready** - MCP server for Claude Code and other AI assistants
- **CLI first** - Fast terminal interface for developers

## Data model

Tickets are local-first and stored in SQLite (`.pm/cache.db`). External provider data
(e.g., Linear) is optional and linked via cached external items when available.

## Installation

### Prerequisites

- Python 3.10+


### From Source

```bash
git clone https://github.com/Semfora-AI/semfora-pm.git
cd semfora-pm
pip install -e .
```

## Configuration

Set your Linear API key(optional):

```bash
# Environment variable (recommended)
export LINEAR_API_KEY=lin_api_...

# Or configure via CLI
semfora-pm auth setup
```

Initialize in your project to link it to a Linear team:

```bash
cd your-project
semfora-pm init
```

This creates a `.pm/config.json` linking your project to Linear.

## Basic Usage

### Check sprint status

```bash
semfora-pm sprint status
```

Shows tickets by state: In Progress, In Review, Todo.

### View ticket details

```bash
semfora-pm show SEM-123
```

Get full ticket context including description, acceptance criteria, and blockers.

### List tickets

```bash
# All tickets in current sprint
semfora-pm sprint status

# Filter by state
semfora-pm tickets search "authentication"
```

### Update ticket status

```bash
semfora-pm tickets update SEM-123 -s "In Progress"
semfora-pm tickets update SEM-123 -s "Done"
```

### Get next ticket suggestion

```bash
semfora-pm sprint suggest
```

AI-powered suggestion for what to work on next based on priority and dependencies.

## Documentation

For detailed documentation including MCP integration and AI workflows, visit:

**[semfora.com/docs/pm](https://semfora.com/docs/pm)**

## Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Setup

```bash
git clone https://github.com/Semfora-AI/semfora-pm.git
cd semfora-pm
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Part of the [Semfora](https://semfora.com) suite of code intelligence tools.
