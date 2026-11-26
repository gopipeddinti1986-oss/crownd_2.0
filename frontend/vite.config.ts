import { defineConfig } from 'vite'; import react from '@vitejs/plugin-react';

const apiProxyTarget = process.env.CROWND_API_PROXY_TARGET || 'http://127.0.0.1:8000';

export default defineConfig({plugins:[react()],server:{host:'0.0.0.0',allowedHosts:true,proxy:{'/api/v1':{target:apiProxyTarget,changeOrigin:true,configure(proxy){proxy.on('proxyReq',(proxyReq,req)=>{if(req.headers.host)proxyReq.setHeader('x-forwarded-host',req.headers.host);proxyReq.setHeader('x-forwarded-for',req.socket.remoteAddress||'unknown');});}}}},preview:{host:'0.0.0.0',allowedHosts:true}});
