import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, FakeNotifyCharacteristic, FakeWriteCharacteristic, toHex } from './support.ts';
import {
  BLE_DEVICE_NAME,
  BLE_RX_UUID,
  BLE_SERVICE_UUID,
  BLE_STATUS_UUID,
  BLE_TX_UUID,
  WebBluetoothTransport,
} from '../src/webbluetooth.ts';

describe('Bridge identifiers', () => {
  test('the service, RX, TX and status UUIDs and the device name are the bridge values', () => {
    assert.equal(BLE_DEVICE_NAME, 'Movetrics-BLE');
    assert.equal(BLE_SERVICE_UUID, '6e400001-b5a3-f393-e0a9-e50e24dcca9e');
    assert.equal(BLE_RX_UUID, '6e400002-b5a3-f393-e0a9-e50e24dcca9e');
    assert.equal(BLE_TX_UUID, '6e400003-b5a3-f393-e0a9-e50e24dcca9e');
    assert.equal(BLE_STATUS_UUID, '52e528e4-f391-4f88-a43a-3d911f82e040');
  });
});

describe('WebBluetoothTransport', () => {
  test('subscribes to TX before open() resolves, with the listener attached first', async () => {
    const notify = new FakeNotifyCharacteristic();
    const write = new FakeWriteCharacteristic();
    const transport = await WebBluetoothTransport.open({ notify, write });
    try {
      assert.deepEqual(notify.log, ['add:characteristicvaluechanged', 'startNotifications']);
      assert.equal(notify.listenerCount, 1);
    } finally {
      await transport.close();
    }
  });

  test('each notification becomes a chunk, copied at the time it arrives', async () => {
    const notify = new FakeNotifyCharacteristic();
    const transport = await WebBluetoothTransport.open({ notify, write: new FakeWriteCharacteristic() });
    const received: string[] = [];
    const reading = (async () => {
      for await (const chunk of transport.chunks) received.push(toHex(chunk));
    })();
    const payload = bytesOf('beef011b06e3440404');
    notify.notify(payload);
    payload.fill(0);
    notify.notify(bytesOf('00ff'));
    await transport.close();
    await reading;
    assert.deepEqual(received, ['beef011b06e3440404', '00ff']);
  });

  test('a write goes to the RX characteristic with response, and the bytes are copied', async () => {
    const write = new FakeWriteCharacteristic();
    const transport = await WebBluetoothTransport.open({ notify: new FakeNotifyCharacteristic(), write });
    try {
      const frame = bytesOf('feed0000239dd80404');
      const pending = transport.write(frame);
      frame.fill(0);
      await pending;
      assert.deepEqual(write.written, ['feed0000239dd80404']);
    } finally {
      await transport.close();
    }
  });

  test('writes never overlap, because the link allows one ATT write at a time', async () => {
    const write = new FakeWriteCharacteristic();
    const transport = await WebBluetoothTransport.open({ notify: new FakeNotifyCharacteristic(), write });
    try {
      let release: () => void = () => undefined;
      write.gate = new Promise<void>((resolve) => {
        release = resolve;
      });
      const first = transport.write(bytesOf('01'));
      const second = transport.write(bytesOf('02'));
      await new Promise((resolve) => setTimeout(resolve, 5));
      assert.equal(write.maxInFlight, 1);
      write.gate = null;
      release();
      await Promise.all([first, second]);
      assert.deepEqual(write.written, ['01', '02']);
      assert.equal(write.maxInFlight, 1);
    } finally {
      await transport.close();
    }
  });

  test('a failed subscription removes the listener and is raised', async () => {
    const notify = new FakeNotifyCharacteristic();
    notify.failStart = new Error('GATT operation failed');
    await assert.rejects(WebBluetoothTransport.open({ notify, write: new FakeWriteCharacteristic() }), /GATT operation failed/);
    assert.equal(notify.listenerCount, 0);
    assert.deepEqual(notify.log, ['add:characteristicvaluechanged', 'startNotifications', 'remove:characteristicvaluechanged']);
  });

  test('close stops notifications, detaches the listener, ends the chunks, and refuses later writes', async () => {
    const notify = new FakeNotifyCharacteristic();
    const transport = await WebBluetoothTransport.open({ notify, write: new FakeWriteCharacteristic() });
    await transport.close();
    await transport.close();
    assert.equal(notify.listenerCount, 0);
    assert.deepEqual(notify.log.slice(-2), ['remove:characteristicvaluechanged', 'stopNotifications']);
    const drained: Uint8Array[] = [];
    for await (const chunk of transport.chunks) drained.push(chunk);
    assert.deepEqual(drained, []);
    await assert.rejects(transport.write(bytesOf('00')), /closed/);
  });
});
