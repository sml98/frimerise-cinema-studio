import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import cookieParser from 'cookie-parser';
import express from 'express';
import { JobQueueRunner } from './src/server/pipeline.ts';
import { createStudioRouter } from './src/server/routes.ts';
import { StudioStore } from './src/server/store.ts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const BASE_DIR = __dirname;

export function createApp(baseDir = BASE_DIR) {
  const app = express();
  const store = new StudioStore(baseDir);
  const runner = new JobQueueRunner(store);

  app.set('trust proxy', true);
  app.use(express.json({ limit: '10mb' }));
  app.use(cookieParser());

  // Security headers compatible with iframe preview hosting
  app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    if (req.path.startsWith('/api/')) {
      res.setHeader('Cache-Control', 'no-store');
    }
    next();
  });

  // Static mounts (strictly allowlisted subfolders — never root data/)
  app.use('/static', express.static(path.join(baseDir, 'web', 'static')));
  app.use('/assets', express.static(path.join(baseDir, 'assets')));
  app.use('/outputs', express.static(path.join(baseDir, 'outputs')));
  app.use('/data/logos', express.static(path.join(baseDir, 'data', 'logos')));
  app.use('/data/ref_cache', express.static(path.join(baseDir, 'data', 'ref_cache')));

  app.use(createStudioRouter(store, runner));

  return { app, store, runner };
}

const isMain = (() => {
  if (!process.argv[1]) return false;
  try {
    return fs.realpathSync(path.resolve(process.argv[1])) === fs.realpathSync(__filename);
  } catch {
    return path.resolve(process.argv[1]) === __filename;
  }
})();

if (isMain) {
  const PORT = Number(process.env.PORT || 3000);
  const { app } = createApp(BASE_DIR);
  app.listen(PORT, '0.0.0.0', () => {
    console.log(`[FrimeRise Studio] Express server running at http://0.0.0.0:${PORT}`);
  });
}
