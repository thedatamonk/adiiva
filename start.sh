#!/usr/bin/env bash
set -e

# Ensure server/.env exists
if [ ! -f server/.env ]; then
    echo "Error: server/.env file not found. Run 'cp server/.env.example server/.env' and fill in your API keys first."
    exit 1
fi

# Generate JWT_SECRET if empty or missing
if ! grep -q "^JWT_SECRET=.\+" server/.env; then
    SECRET=$(openssl rand -hex 32)
    if grep -q "^JWT_SECRET=" server/.env; then
        sed -i.bak "s/^JWT_SECRET=.*/JWT_SECRET=${SECRET}/" server/.env && rm -f server/.env.bak
    else
        echo "JWT_SECRET=${SECRET}" >> server/.env
    fi
    echo "Generated JWT_SECRET"
fi

docker compose up --build
