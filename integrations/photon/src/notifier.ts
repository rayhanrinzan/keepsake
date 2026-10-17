// Delivery transports. The alert logic only sees `Notifier`, so another channel can replace iMessage.

export interface Notifier {
  readonly name: string;
  /** Deliver one text. Rejects on failure; callers decide about retries (we don't retry). */
  send(recipient: string, text: string): Promise<void>;
}

/** The part of a Spectrum space the notifier needs. */
export interface SendableSpace {
  send(text: string): Promise<unknown>;
}

/**
 * Sends through Photon Spectrum's iMessage provider (the project's assigned line).
 * `openSpace` is `(to) => imessage(app).space.create(to)`, kept injectable for tests.
 */
export class SpectrumIMessageNotifier implements Notifier {
  readonly name = "photon-imessage";

  constructor(private readonly openSpace: (recipient: string) => Promise<SendableSpace>) {}

  async send(recipient: string, text: string): Promise<void> {
    const space = await this.openSpace(recipient);
    await space.send(text);
  }
}
