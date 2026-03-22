import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';

export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/connect': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
            '/token': {
                target: 'http://localhost:8000',
                changeOrigin: true,
            },
        },
    },
});
