import { type Transport } from './transport.js';
export declare const BLE_DEVICE_NAME = "Movetrics-BLE";
export declare const BLE_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
export declare const BLE_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
export declare const BLE_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
export declare const BLE_STATUS_UUID = "52e528e4-f391-4f88-a43a-3d911f82e040";
export interface BleNotifyCharacteristic {
    readonly value?: DataView | null | undefined;
    startNotifications(): Promise<unknown>;
    stopNotifications(): Promise<unknown>;
    addEventListener(type: 'characteristicvaluechanged', listener: () => void): void;
    removeEventListener(type: 'characteristicvaluechanged', listener: () => void): void;
}
export interface BleWriteCharacteristic {
    writeValueWithResponse(value: Uint8Array): Promise<void>;
}
export interface BleCharacteristics {
    readonly notify: BleNotifyCharacteristic;
    readonly write: BleWriteCharacteristic;
}
export declare class WebBluetoothTransport implements Transport {
    #private;
    readonly chunks: AsyncIterable<Uint8Array>;
    private constructor();
    static open(characteristics: BleCharacteristics): Promise<WebBluetoothTransport>;
    write(data: Uint8Array): Promise<void>;
    close(): Promise<void>;
}
