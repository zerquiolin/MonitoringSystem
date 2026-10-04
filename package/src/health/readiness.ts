export type Check = { check: (signal: AbortSignal) => Promise<boolean>; critical?: boolean };
export class Readiness {
  ready = true; private pending?: Promise<boolean>; private hung = new Set<string>(); private cacheUntil = 0; private cached = true;
  constructor(private checks: Record<string, Check>, private timeout = 2000, private cacheMs = 250) {}
  async evaluate(): Promise<boolean> {
    if (!this.ready) return false;
    if (this.pending) return this.pending;
    if (Date.now() < this.cacheUntil) return this.cached;
    this.pending = (async () => {
      const results = await Promise.all(Object.entries(this.checks).map(async ([name,c]) => {
        if (this.hung.has(name)) return c.critical === false;
        const abort = new AbortController(); let timer: NodeJS.Timeout | undefined;
        this.hung.add(name);
        const task = Promise.resolve().then(() => c.check(abort.signal)).catch(() => false).finally(() => this.hung.delete(name));
        const ok = await Promise.race([task, new Promise<boolean>(r => { timer = setTimeout(() => { abort.abort(); r(false); }, this.timeout); })]);
        clearTimeout(timer); return ok || c.critical === false;
      }));
      this.cached = results.every(Boolean); this.cacheUntil = Date.now() + this.cacheMs; return this.cached;
    })().finally(() => { this.pending = undefined; });
    return this.pending;
  }
}
