#!/usr/bin/env bash
set -e

# Ensure .env exists
if [ ! -f .env ]; then
    echo "Error: .env file not found. Run 'cp .env.example .env' and fill in your API keys first."
    exit 1
fi

# Generate JWT_SECRET if empty or missing
if ! grep -q "^JWT_SECRET=.\+" .env; then
    SECRET=$(openssl rand -hex 32)
    if grep -q "^JWT_SECRET=" .env; then
        sed -i.bak "s/^JWT_SECRET=.*/JWT_SECRET=${SECRET}/" .env && rm -f .env.bak
    else
        echo "JWT_SECRET=${SECRET}" >> .env
    fi
    echo "Generated JWT_SECRET"
fi

docker compose up --build
