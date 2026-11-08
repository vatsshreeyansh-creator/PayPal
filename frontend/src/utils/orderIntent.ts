// A key identifies one order intent; OrderTicket retains it when a request fails.
export function createOrderIntentKey(): string {
  return `web-${crypto.randomUUID()}`;
}

