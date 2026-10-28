# Web example

A static page that drives the FDT host link from a browser: connect over USB or Bluetooth, read the
firmware version and the status, start the stream, show the last 20 frames, and stop.

Browser support is UNVERIFIED for this SDK. No pinned repository uses Web Serial or Web Bluetooth
(`../../docs/02-transports.md`, U1). Run the page as a bench test before relying on it.

## Run it

The page imports the built SDK from `../../ts/dist`, so serve the `sdk/` folder, not this one:

```sh
cd sdk/ts && npm install && npm run build   # once, to create dist/
cd ../                                      # the sdk/ folder
python3 -m http.server 8080
```

Open `http://localhost:8080/examples/web/` in Chrome or Edge. Web Serial and Web Bluetooth need a
secure context. `localhost` counts as one.

## What each control does

- **Connect USB** opens a port picker (Web Serial). It opens the port at 1,500,000 baud, 8N1, no flow
  control, then reads the version and the status, and starts the stream. Where the browser allows it,
  it clears DTR and RTS after open. The browser effect is UNVERIFIED (see the USB note in `../../ts/README.md`).
- **Connect Bluetooth** opens a device picker filtered on the bridge's service UUID. The bridge
  advertises as `Movetrics-BLE`. It subscribes to the TX characteristic before writing anything.
- **Stop** sends STOP_STREAM (0x05). The link stays open.
- **Disconnect** closes the client and the link.

While a session is open, the page sends KEEP_ALIVE with 600 s every 30 s, as the Android app does
(`../../docs/03-host-link-framing.md`, section 3.10).

The Status panel shows the general record and each platform record. A battery value of 255 means
"not measured". The stream table shows the last 20 frames with raw wire
integers. Their units are not verified (`../../vectors/README.md`, not covered 11).

## Files

- `index.html`: the page and its styles. Text is set with `textContent`, so device data is never
  parsed as HTML.
- `app.js`: the page logic. It imports `../../ts/dist/index.js` and nothing else.
