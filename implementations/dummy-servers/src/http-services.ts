import express, { type NextFunction, type Request, type Response } from 'express';
import Fastify from 'fastify';
import { DatabaseSync } from 'node:sqlite';
import type { Monitoring } from '@portable-observability/sdk';
import type { Server } from 'node:http';
import type { DemoFaultState } from './demo-config.js';

export type HttpDemoRole = 'orders' | 'catalog';

export interface DemoServer {
  close(): Promise<void>;
}

interface ProductResponse {
  status: 'ok';
  price: number;
}

const database = new DatabaseSync(':memory:');
database.exec("CREATE TABLE products(id TEXT PRIMARY KEY, price INTEGER); INSERT INTO products VALUES('demo',42)");

function readProduct(url: string): Promise<ProductResponse> {
  return new Promise((resolve, reject) => {
    const request = fetch(url, { signal: AbortSignal.timeout(2_000) });
    void request.then(async (response) => {
      if (!response.ok) throw new Error(`Catalog returned HTTP ${response.status}`);
      const value: unknown = await response.json();
      if (typeof value !== 'object' || value === null || !('status' in value) || !('price' in value)
        || value.status !== 'ok' || typeof value.price !== 'number') {
        throw new Error('Catalog returned an invalid product response');
      }
      resolve({ status: 'ok', price: value.price });
    }).catch(reject);
  });
}

const delay = (milliseconds: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

function closeHttpServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}

export async function start(
  role: HttpDemoRole,
  port: number,
  monitoring: Monitoring,
  state: DemoFaultState,
): Promise<DemoServer> {
  if (role === 'orders') {
    const app = express();
    app.use(monitoring.middleware());
    app.get('/health', monitoring.healthHandler);
    app.get('/ready', monitoring.readyHandler);

    app.get('/orders/:id', async (request: Request, response: Response, next: NextFunction) => {
      try {
        const item = await monitoring.withSpan('orders.lookup', {}, async () => {
          if (state.slowMs > 0) await delay(state.slowMs);
          if (state.error) throw new Error('Injected order failure');
          const product = await readProduct('http://127.0.0.1:4102/products/demo');
          monitoring.logger.info('Order lookup completed', {
            operation: 'lookup',
            password: 'SENSITIVE_FIXTURE',
            product,
            orderId: request.params.id,
          });
          return product;
        });
        response.json({ status: 'ok', item });
      } catch (error: unknown) {
        next(error);
      }
    });

    app.get('/slow', async (_request: Request, response: Response) => {
      await delay(state.slowMs || 1_000);
      response.json({ status: 'ok' });
    });
    app.get('/error', (_request: Request, _response: Response, next: NextFunction) => {
      next(new TypeError('Injected caught exception'));
    });
    app.get('/stream', (_request: Request, response: Response) => {
      response.write('started\n');
      setTimeout(() => response.end('finished\n'), 1_000);
    });

    app.use(monitoring.errorMiddleware());
    app.use((_error: unknown, _request: Request, response: Response, _next: NextFunction) => {
      response.status(500).json({ status: 'error' });
    });

    const server = await new Promise<Server>((resolve, reject) => {
      const listeningServer = app.listen(port, '0.0.0.0', () => resolve(listeningServer));
      listeningServer.once('error', reject);
    });
    return { close: () => closeHttpServer(server) };
  }

  const app = Fastify();
  await monitoring.fastifyPlugin(app);
  app.get('/health', async (_request, reply) => {
    reply.hijack();
    monitoring.healthHandler(_request.raw, reply.raw);
  });
  app.get('/ready', async (_request, reply) => {
    reply.hijack();
    await monitoring.readyHandler(_request.raw, reply.raw);
  });
  app.get<{ Params: { id: string } }>('/products/:id', async (request) =>
    monitoring.withSpan('catalog.database.select', { operation: 'select', productId: request.params.id }, async () => {
      if (state.dependencySlowMs > 0) await delay(state.dependencySlowMs);
      if (state.dependency) throw new Error('Database fixture unavailable');
      const result = database.prepare('SELECT price FROM products WHERE id=?').get(request.params.id);
      if (!result || typeof result.price !== 'number') throw new Error('Product does not exist');
      monitoring.logger.info('Catalog database query completed', { operation: 'select' });
      return { status: 'ok', price: result.price } satisfies ProductResponse;
    }));

  await app.listen({ host: '0.0.0.0', port });
  return { close: () => app.close() };
}
