// The byte pipe the client runs on. Implementations: WebSerialTransport and
// WebBluetoothTransport (browser), or any object with the same shape (tests, Node).

export interface Transport {
  // Sends one already-framed request. Resolves when the bytes are handed to the link.
  write(data: Uint8Array): Promise<void>;
  // Received bytes, in order, in chunks of any size. Ends when the link closes.
  readonly chunks: AsyncIterable<Uint8Array>;
  close(): Promise<void>;
}

interface Pending<T> {
  resolve(result: IteratorResult<T>): void;
  reject(error: unknown): void;
}

// A FIFO that can be consumed with for-await. Used for transport chunks and for
// stream frames. With a backlog limit, the oldest item is dropped and counted.
export class AsyncQueue<T> implements AsyncIterable<T> {
  readonly #items: T[] = [];
  readonly #waiting: Pending<T>[] = [];
  readonly #maxBacklog: number;
  #closed = false;
  #failed = false;
  #error: unknown = undefined;
  #dropped = 0;

  constructor(maxBacklog = Number.POSITIVE_INFINITY) {
    this.#maxBacklog = maxBacklog;
  }

  get dropped(): number {
    return this.#dropped;
  }

  get closed(): boolean {
    return this.#closed;
  }

  push(item: T): void {
    if (this.#closed) return;
    const waiter = this.#waiting.shift();
    if (waiter) {
      waiter.resolve({ value: item, done: false });
      return;
    }
    if (this.#items.length >= this.#maxBacklog) {
      this.#items.shift();
      this.#dropped++;
    }
    this.#items.push(item);
  }

  close(error?: unknown): void {
    if (this.#closed) return;
    this.#closed = true;
    if (error !== undefined) {
      this.#failed = true;
      this.#error = error;
    }
    for (const waiter of this.#waiting.splice(0)) {
      if (this.#failed) waiter.reject(this.#error);
      else waiter.resolve({ value: undefined, done: true });
    }
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    // No return() method: breaking out of a for-await loop does not close the queue.
    return {
      next: (): Promise<IteratorResult<T>> => this.#next(),
    };
  }

  #next(): Promise<IteratorResult<T>> {
    if (this.#items.length > 0) {
      return Promise.resolve({ value: this.#items.shift() as T, done: false });
    }
    if (this.#closed) {
      if (this.#failed) return Promise.reject(this.#error);
      return Promise.resolve({ value: undefined, done: true });
    }
    return new Promise<IteratorResult<T>>((resolve, reject) => {
      this.#waiting.push({ resolve, reject });
    });
  }
}
