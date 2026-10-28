// Web Serial transport for the USB link. The adapter is an FTDI FT232R on USART3, at
// 1,500,000 baud, 8 data bits, one stop bit, no parity and no flow control
// (docs/02-transports.md, USB row; the firmware). The browser side is UNVERIFIED:
// no pinned repository uses Web Serial (docs/02-transports.md, U1).
import { AsyncQueue } from "./transport.js";
// The options the USB link opens with. the firmware sets the default baud rate.
export const SERIAL_OPTIONS = {
    baudRate: 1500000,
    dataBits: 8,
    stopBits: 1,
    parity: 'none',
    flowControl: 'none',
};
export class WebSerialTransport {
    #port;
    #reader;
    #writer;
    #input = new AsyncQueue();
    #pump;
    #closed = false;
    chunks = this.#input;
    constructor(port, reader, writer) {
        this.#port = port;
        this.#reader = reader;
        this.#writer = writer;
        this.#pump = this.#readAll();
    }
    // Opens the port with SERIAL_OPTIONS, clears DTR and RTS where the platform has setSignals,
    // and takes its streams. If the setSignals call rejects or a stream is missing, the port is
    // closed again and the error is raised.
    static async open(port) {
        await port.open({ ...SERIAL_OPTIONS });
        try {
            if (typeof port.setSignals === 'function') {
                // The Android app's USB path never sets either line, source only:
                // android:app/src/main/java/com/movetrics/fdt/android/NoModemControlFtdiPort.java:9 and 16-26.
                // This call clears both lines, so neither is asserted. fdt:docs/architecture.md:44 (an
                // earlier SDK note, not firmware fact) says opening a port may affect modem lines and that
                // DTR/RTS choices are to be recorded. The first hardware run must check for reset-like
                // behaviour. The browser effect is UNVERIFIED.
                await port.setSignals({ dataTerminalReady: false, requestToSend: false });
            }
            const readable = port.readable;
            const writable = port.writable;
            if (readable === null || writable === null) {
                throw new Error('the serial port opened without its readable and writable streams');
            }
            return new WebSerialTransport(port, readable.getReader(), writable.getWriter());
        }
        catch (error) {
            await port.close().catch(() => undefined);
            throw error;
        }
    }
    async write(data) {
        if (this.#closed)
            throw new Error('the serial port is closed');
        await this.#writer.write(data.slice());
    }
    async close() {
        if (this.#closed)
            return;
        this.#closed = true;
        await this.#reader.cancel().catch(() => undefined);
        await this.#pump;
        this.#writer.releaseLock();
        await this.#port.close();
    }
    async #readAll() {
        try {
            for (;;) {
                const result = await this.#reader.read();
                if (result.done)
                    break;
                if (result.value !== undefined)
                    this.#input.push(result.value.slice());
            }
            this.#input.close();
        }
        catch (error) {
            this.#input.close(error);
        }
        try {
            this.#reader.releaseLock();
        }
        catch {
            // The reader is already released.
        }
    }
}
