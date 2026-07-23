export type IdempotencyAttempt = { signature: string; key: string };

export function idempotencyAttempt(
  current: IdempotencyAttempt | null,
  signature: string,
  createKey: () => string = () => crypto.randomUUID(),
): IdempotencyAttempt {
  return current?.signature === signature ? current : { signature, key: createKey() };
}
