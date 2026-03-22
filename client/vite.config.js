import { defineConfig } from 'vite';

export default defineConfig({
    server: {
        proxy: {
            '/token': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/ws': {
                target: 'ws://localhost:8000',
                ws: true,
            },
            '/health': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/metrics': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/admin': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
});
