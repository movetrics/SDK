// Web example for the FDT host link: connect over USB (Web Serial) or Bluetooth (Web
// Bluetooth through the ESP32-S3 bridge), read the firmware version and the status, start
// the stream, show the last 20 frames, and stop. Served from the sdk/ folder, so that the
// built SDK at ../../ts/dist is reachable (see README.md in this folder).

import {
  BLE_SERVICE_UUID,
  BLE_RX_UUID,
  BLE_TX_UUID,
  FdtClient,
  WebBluetoothTransport,
  WebSerialTransport,
} from '../../ts/dist/index.js';

// The Android app writes KEEP_ALIVE with 600 s every 30 s while a session is open
// (docs/03-host-link-framing.md, section 3.10).
const KEEP_ALIVE_SECONDS = 600;
const KEEP_ALIVE_EVERY_MS = 30000;
const LAST_ROWS = 20;

const ui = {
  connectUsb: document.getElementById('connect-usb'),
  connectBle: document.getElementById('connect-ble'),
  stop: document.getElementById('stop'),
  disconnect: document.getElementById('disconnect'),
  message: document.getElementById('message'),
  version: document.getElementById('version'),
  status: document.getElementById('status'),
  count: document.getElementById('count'),
  dropped: document.getElementById('dropped'),
  rows: document.getElementById('rows'),
};

let session = null; // the FdtClient for the open link
let keepAliveTimer = null;
let frameTotal = 0;
const recent = [];
let renderQueued = false;

function setMessage(text, isError = false) {
  ui.message.textContent = text;
  ui.message.className = isError ? 'error' : '';
}

function showError(error) {
  setMessage(error instanceof Error ? error.message : String(error), true);
}

function setConnected(connected) {
  ui.connectUsb.disabled = connected || !('serial' in navigator);
  ui.connectBle.disabled = connected || !('bluetooth' in navigator);
  ui.stop.disabled = true;
  ui.disconnect.disabled = !connected;
}

function clearPanels() {
  ui.version.textContent = '';
  ui.status.replaceChildren();
  ui.count.textContent = '0';
  ui.dropped.textContent = '0';
  recent.length = 0;
  frameTotal = 0;
  renderRows();
}

// ---- Status and version panels -----------------------------------------------------

function describeBattery(value) {
  if (value === null) return 'not reported by this record';
  if (value === 255) return 'not measured';
  return `${value} %`;
}

function recordItem(title, record) {
  const item = document.createElement('section');
  const heading = document.createElement('h3');
  heading.textContent = title;
  const list = document.createElement('dl');
  const entries = [
    ['Platform address', String(record.platformAddress)],
    ['Error flags', `0x${record.errorFlags.toString(16).padStart(8, '0')}`],
    ['Battery', describeBattery(record.batterySOC)],
    ['Serial parameters', record.serialParams || '(empty)'],
    ['Calibration X, Y, Z', `${record.calibrationFactorX}, ${record.calibrationFactorY}, ${record.calibrationFactorZ}`],
  ];
  for (const [label, value] of entries) {
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value;
    list.append(term, detail);
  }
  item.append(heading, list);
  return item;
}

function renderStatus(status) {
  const children = [recordItem('General record', status.general)];
  for (const record of status.platforms) {
    children.push(recordItem(`Platform ${record.platformAddress}`, record));
  }
  ui.status.replaceChildren(...children);
}

// ---- Stream table ------------------------------------------------------------------

function addFrame(frame, current) {
  frameTotal += 1;
  recent.push(frame);
  if (recent.length > LAST_ROWS) recent.shift();
  ui.count.textContent = String(frameTotal);
  ui.dropped.textContent = String(current.droppedFrames);
  if (!renderQueued) {
    renderQueued = true;
    requestAnimationFrame(() => {
      renderQueued = false;
      renderRows();
    });
  }
}

function renderRows() {
  const body = ui.rows;
  body.replaceChildren();
  recent.forEach((frame, index) => {
    const row = document.createElement('tr');
    const cells = [
      frameTotal - recent.length + index + 1,
      frame.platformAddress,
      frame.timeStamp,
      frame.forceX,
      frame.forceY,
      frame.forceZ,
      frame.momentX,
      frame.momentY,
      frame.momentZ,
    ];
    for (const value of cells) {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.append(cell);
    }
    body.append(row);
  });
}

// ---- Session -----------------------------------------------------------------------

async function startSession(transport) {
  await endSession();
  const current = new FdtClient(transport);
  session = current;
  setConnected(true);
  clearPanels();
  keepAliveTimer = setInterval(() => {
    current.keepAlive(KEEP_ALIVE_SECONDS).catch(showError);
  }, KEEP_ALIVE_EVERY_MS);
  try {
    setMessage('Reading the firmware version and the status.');
    const version = await current.getFwVersion();
    ui.version.textContent = `STM32 firmware ${version.stm32FW}, ESP32 firmware ${version.esp32FW}`;
    renderStatus(await current.getStatus());
    await current.startStream();
    ui.stop.disabled = false;
    setMessage('Streaming. Press Stop to end the stream.');
    readFrames(current);
  } catch (error) {
    showError(error);
  }
}

async function readFrames(current) {
  try {
    for await (const frame of current.frames()) {
      addFrame(frame, current);
    }
    if (session === current) setMessage('The stream has ended.');
  } catch (error) {
    if (session === current) showError(error);
  }
}

async function endSession() {
  if (keepAliveTimer !== null) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
  const current = session;
  session = null;
  if (current !== null) {
    try {
      await current.close();
    } catch (error) {
      showError(error);
    }
  }
  setConnected(false);
}

async function connectUsb() {
  try {
    const port = await navigator.serial.requestPort();
    const transport = await WebSerialTransport.open(port);
    await startSession(transport);
  } catch (error) {
    showError(error);
  }
}

async function connectBluetooth() {
  let device = null;
  try {
    device = await navigator.bluetooth.requestDevice({
      filters: [{ services: [BLE_SERVICE_UUID] }],
      optionalServices: [BLE_SERVICE_UUID],
    });
    device.addEventListener('gattserverdisconnected', () => {
      if (session !== null) setMessage('The Bluetooth link was lost.', true);
      endSession();
    });
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService(BLE_SERVICE_UUID);
    const rx = await service.getCharacteristic(BLE_RX_UUID);
    const tx = await service.getCharacteristic(BLE_TX_UUID);
    const transport = await WebBluetoothTransport.open({ notify: tx, write: rx });
    await startSession(transport);
  } catch (error) {
    showError(error);
    if (device !== null && device.gatt?.connected) device.gatt.disconnect();
  }
}

async function stopStream() {
  if (session === null) return;
  ui.stop.disabled = true;
  try {
    await session.stopStream();
    setMessage('Stream stopped. The link is still open.');
  } catch (error) {
    showError(error);
    ui.stop.disabled = false;
  }
}

ui.connectUsb.addEventListener('click', connectUsb);
ui.connectBle.addEventListener('click', connectBluetooth);
ui.stop.addEventListener('click', stopStream);
ui.disconnect.addEventListener('click', () => {
  endSession();
  setMessage('Disconnected.');
});

if (!('serial' in navigator)) setMessage('Web Serial is not available in this browser. Use Bluetooth or a Chromium-based browser.');
else if (!('bluetooth' in navigator)) setMessage('Web Bluetooth is not available in this browser. Use USB.');
else setMessage('Choose USB or Bluetooth to connect.');
setConnected(false);
