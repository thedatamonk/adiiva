#!/usr/bin/env bash
set -e

# Copy .env.example to .env if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
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
