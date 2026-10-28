// Web Bluetooth transport for the wireless link. The phone talks to the ESP32-S3 bridge
// (esp32-bridge/MovetricsBridge), which relays the bytes to the controller's UART4.
// The UUIDs and the device name are in the firmware:22-29.
//
// The bridge relays bytes only while one phone is subscribed to the TX characteristic,
// and it drops any command that arrives before that ("Enable return notifications before
// sending any command", MovetricsBridge.ino:116). open() therefore subscribes before it returns.
// Writes use writeValueWithResponse only, because the bridge's RX characteristic has the WRITE
// property alone (MovetricsBridge.ino:224-226).
// The browser side is UNVERIFIED (docs/02-transports.md, U1).
import { AsyncQueue } from "./transport.js";
export const BLE_DEVICE_NAME = 'Movetrics-BLE'; // BridgeConfig.h:22
export const BLE_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e'; // BridgeConfig.h:25
export const BLE_RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e'; // BridgeConfig.h:26, phone to bridge
export const BLE_TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e'; // BridgeConfig.h:27, bridge to phone
// Read-only text diagnostics (key=value). Not part of the FDT protocol (BridgeConfig.h:28-29).
export const BLE_STATUS_UUID = '52e528e4-f391-4f88-a43a-3d911f82e040';
function copyOf(view) {
    return Uint8Array.from(new Uint8Array(view.buffer, view.byteOffset, view.byteLength));
}
export class WebBluetoothTransport {
    #notify;
    #write;
    #input = new AsyncQueue();
    #onValue = () => {
        const value = this.#notify.value;
        if (value)
            this.#input.push(copyOf(value));
    };
    #tail = Promise.resolve();
    #closed = false;
    chunks = this.#input;
    constructor(notify, write) {
        this.#notify = notify;
        this.#write = write;
    }
    // Subscribes to TX and returns the transport. The listener is attached first, so no
    // notification is missed. If the subscription fails, the listener is removed and the error is raised.
    static async open(characteristics) {
        const transport = new WebBluetoothTransport(characteristics.notify, characteristics.write);
        characteristics.notify.addEventListener('characteristicvaluechanged', transport.#onValue);
        try {
            await characteristics.notify.startNotifications();
        }
        catch (error) {
            characteristics.notify.removeEventListener('characteristicvaluechanged', transport.#onValue);
            transport.#input.close();
            throw error;
        }
        return transport;
    }
    // Writes are queued one at a time, because the link allows one ATT write at a time.
    write(data) {
        const bytes = data.slice();
        const sent = this.#tail.then(() => {
            if (this.#closed)
                throw new Error('the Bluetooth link is closed');
            return this.#write.writeValueWithResponse(bytes);
        });
        this.#tail = sent.then(() => undefined, () => undefined);
        return sent;
    }
    async close() {
        if (this.#closed)
            return;
        this.#closed = true;
        this.#notify.removeEventListener('characteristicvaluechanged', this.#onValue);
        this.#input.close();
        try {
            await this.#notify.stopNotifications();
        }
        catch {
            // The device may already be gone. The link is closed either way.
        }
    }
}
