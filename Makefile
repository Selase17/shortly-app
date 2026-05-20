
# Makefile — convenience commands for shortly-app local dev
#
# Usage:  make <target>
# Run `make help` to see all targets with descriptions.

.PHONY: help build up down restart logs ps test lint clean rebuild

# Default target shown when running just `make`
.DEFAULT_GOAL := help

help:  ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

build:  ## Build the Docker image
	docker compose build

up:  ## Start the stack (detached)
	docker compose up -d
	@echo ""
	@echo "Stack is up. Try: curl http://localhost:5000/healthz"
	@echo "Logs:             make logs"
	@echo "Stop:             make down"

down:  ## Stop and remove the stack
	docker compose down

restart:  ## Restart all services
	docker compose restart

logs:  ## Tail logs from all services
	docker compose logs -f

ps:  ## Show running containers
	docker compose ps

test:  ## Run pytest locally (requires .venv active)
	pytest -v

lint:  ## Run ruff locally
	ruff check .

rebuild:  ## Rebuild from scratch (no cache)
	docker compose build --no-cache

clean:  ## Remove containers, networks, AND volumes (destructive)
	docker compose down -v