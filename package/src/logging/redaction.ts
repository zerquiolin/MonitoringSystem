const sensitive = /authorization|cookie|password|secret|token|credit.?card|payment|connection.?string|email/i;
export function sanitize(value: unknown, depth = 0, extra: string[] = []): any {
  if (depth > 5) return '[depth limit]';
  if (typeof value === 'string') return value.replace(/(Bearer\s+)\S+/gi, '$1[REDACTED]').replace(/([?&](?:token|password|key|secret)=)[^&\s]*/gi, '$1[REDACTED]').replace(/:\/\/[^/@\s]+:[^/@\s]+@/g, '://[REDACTED]@').slice(0, 4096);
  if (Array.isArray(value)) return value.slice(0, 32).map(v => sanitize(v, depth + 1, extra));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 32).map(([k,v]) => [k, sensitive.test(k) || extra.includes(k) ? '[REDACTED]' : sanitize(v, depth + 1, extra)]));
  return value;
}
