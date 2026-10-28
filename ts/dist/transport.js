// The byte pipe the client runs on. Implementations: WebSerialTransport and
// WebBluetoothTransport (browser), or any object with the same shape (tests, Node).
// A FIFO that can be consumed with for-await. Used for transport chunks and for
// stream frames. With a backlog limit, the oldest item is dropped and counted.
export class AsyncQueue {
    #items = [];
    #waiting = [];
    #maxBacklog;
    #closed = false;
    #failed = false;
    #error = undefined;
    #dropped = 0;
    constructor(maxBacklog = Number.POSITIVE_INFINITY) {
        this.#maxBacklog = maxBacklog;
    }
    get dropped() {
        return this.#dropped;
    }
    get closed() {
        return this.#closed;
    }
    push(item) {
        if (this.#closed)
            return;
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
    close(error) {
        if (this.#closed)
            return;
        this.#closed = true;
        if (error !== undefined) {
            this.#failed = true;
            this.#error = error;
        }
        for (const waiter of this.#waiting.splice(0)) {
            if (this.#failed)
                waiter.reject(this.#error);
            else
                waiter.resolve({ value: undefined, done: true });
        }
    }
    [Symbol.asyncIterator]() {
        // No return() method: breaking out of a for-await loop does not close the queue.
        return {
            next: () => this.#next(),
        };
    }
    #next() {
        if (this.#items.length > 0) {
            return Promise.resolve({ value: this.#items.shift(), done: false });
        }
        if (this.#closed) {
            if (this.#failed)
                return Promise.reject(this.#error);
            return Promise.resolve({ value: undefined, done: true });
        }
        return new Promise((resolve, reject) => {
            this.#waiting.push({ resolve, reject });
        });
    }
}
