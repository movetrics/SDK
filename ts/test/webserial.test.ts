import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { bytesOf, FakeSerialPort, toHex } from './support.ts';
import { SERIAL_OPTIONS, WebSerialTransport } from '../src/webserial.ts';

describe('WebSerialTransport', () => {
  test('opens the port at 1,500,000 baud, 8N1, with no flow control', async () => {
    const port = new FakeSerialPort();
    const transport = await WebSerialTransport.open(port);
    try {
      assert.deepEqual(port.opened, {
        baudRate: 1500000,
        dataBits: 8,
        stopBits: 1,
        parity: 'none',
        flowControl: 'none',
      });
      assert.deepEqual(SERIAL_OPTIONS, port.opened);
    } finally {
      await transport.close();
    }
  });

  test('writes the bytes it is given, as a copy', async () => {
    const port = new FakeSerialPort();
    const transport = await WebSerialTransport.open(port);
    try {
      const frame = bytesOf('feed0000239dd80404');
      const pending = transport.write(frame);
      frame.fill(0);
      await pending;
      assert.deepEqual(port.written.map(toHex), ['feed0000239dd80404']);
    } finally {
      await transport.close();
    }
  });

  test('device bytes arrive as chunks, in order', async () => {
    const port = new FakeSerialPort();
    const transport = await WebSerialTransport.open(port);
    const received: string[] = [];
    const reading = (async () => {
      for await (const chunk of transport.chunks) received.push(toHex(chunk));
    })();
    port.device.push(bytesOf('beef01'));
    port.device.push(bytesOf('1b06e3440404'));
    await transport.close();
    await reading;
    assert.deepEqual(received, ['beef01', '1b06e3440404']);
  });

  test('close cancels the reader, releases the writer, closes the port, and ends the chunks', async () => {
    const port = new FakeSerialPort();
    const transport = await WebSerialTransport.open(port);
    await transport.close();
    await transport.close();
    assert.equal(port.readerCancels, 1);
    assert.equal(port.readerReleases, 1);
    assert.equal(port.writerReleases, 1);
    assert.equal(port.closeCalls, 1);
    assert.equal(port.opened, null);
    const drained: Uint8Array[] = [];
    for await (const chunk of transport.chunks) drained.push(chunk);
    assert.deepEqual(drained, []);
    await assert.rejects(transport.write(bytesOf('00')), /closed/);
  });

  test('an open failure is raised, and the port is not closed', async () => {
    const port = new FakeSerialPort();
    port.failOpen = new Error('access denied');
    await assert.rejects(WebSerialTransport.open(port), /access denied/);
    assert.equal(port.closeCalls, 0);
  });

  test('a port that opens without its streams is closed again and the failure is raised', async () => {
    const port = new FakeSerialPort();
    port.withStreams = false;
    await assert.rejects(WebSerialTransport.open(port), /without its readable and writable streams/);
    assert.equal(port.closeCalls, 1);
  });

  test('after open, DTR and RTS are both cleared, and the call is made while the port is open', async () => {
    const port = new FakeSerialPort();
    const transport = await WebSerialTransport.open(port);
    try {
      assert.deepEqual(port.signalCalls, [
        { signals: { dataTerminalReady: false, requestToSend: false }, portOpen: true },
      ]);
    } finally {
      await transport.close();
    }
  });

  test('a platform without setSignals still opens, and the transport still writes', async () => {
    const port = new FakeSerialPort({ signals: false });
    const transport = await WebSerialTransport.open(port);
    try {
      assert.notEqual(port.opened, null);
      assert.deepEqual(port.signalCalls, []);
      await transport.write(bytesOf('feed0000239dd80404'));
      assert.deepEqual(port.written.map(toHex), ['feed0000239dd80404']);
    } finally {
      await transport.close();
    }
  });

  test('if setSignals rejects, the port is closed again and the error is raised', async () => {
    const port = new FakeSerialPort({ signalsError: new Error('signals refused') });
    await assert.rejects(WebSerialTransport.open(port), /signals refused/);
    assert.equal(port.closeCalls, 1);
    assert.equal(port.opened, null);
  });
});
