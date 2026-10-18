// Delivery transports. The alert logic only sees `Notifier`, so another channel can replace iMessage.

import { attachment } from "spectrum-ts";

/** A photo to send along with a message (JPEG bytes from Keepsake's photo store). */
export interface Photo {
  name: string;
  data: Buffer;
}

export interface Notifier {
  readonly name: string;
  /** Deliver one text, then its photos. Rejects on failure; callers decide about retries (we don't). */
  send(recipient: string, text: string, photos?: Photo[]): Promise<void>;
}

/** The part of a Spectrum space the notifier needs. */
export interface SendableSpace {
  send(...content: unknown[]): Promise<unknown>;
}

/**
 * Sends through Photon Spectrum's iMessage provider (the project's assigned line).
 * `openSpace` is `(to) => imessage(app).space.create(to)`, kept injectable for tests.
 */
export class SpectrumIMessageNotifier implements Notifier {
  readonly name = "photon-imessage";

  constructor(
    private readonly openSpace: (recipient: string) => Promise<SendableSpace>,
    private readonly makeAttachment: (data: Buffer, name: string) => unknown = (data, name) =>
      attachment(data, { mimeType: "image/jpeg", name }),
  ) {}

  async send(recipient: string, text: string, photos: Photo[] = []): Promise<void> {
    const space = await this.openSpace(recipient);
    if (photos.length === 0) {
      await space.send(text);
      return;
    }
    await space.send(text, ...photos.map((p) => this.makeAttachment(p.data, p.name)));
  }
}
